"""Tests for anomaly detection — z-score, high-value overdue, and LLM fallback."""
import sqlite3
import pytest
from contextlib import contextmanager
from unittest.mock import patch

from app.services.anomaly import detect_anomalies


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_db(rows: list) -> contextmanager:
    """Return a context-manager yielding a seeded in-memory SQLite connection."""
    @contextmanager
    def _ctx():
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE transacoes (
                id TEXT, valor REAL, status TEXT,
                cliente TEXT, descricao TEXT, data TEXT
            )
        """)
        conn.executemany("INSERT INTO transacoes VALUES (?,?,?,?,?,?)", rows)
        conn.commit()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    return _ctx()


def _patch_db(rows):
    return patch("app.services.anomaly.get_db", side_effect=lambda: _make_db(rows))


def _patch_settings(api_key: str = ""):
    return patch("app.services.anomaly.settings", deepseek_api_key=api_key)


# ── detect_anomalies ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestDetectAnomalies:

    async def test_empty_db_returns_empty_list(self):
        with _patch_db([]), _patch_settings():
            result = await detect_anomalies()
        assert result == []

    async def test_insufficient_rows_per_client_skips_zscore(self):
        """Fewer than 3 rows per client → z-score skipped, no statistical anomaly."""
        rows = [
            ("txn_001", 100.0, "pago",    "Cliente A", "desc", "2024-01-01"),
            ("txn_002", 200.0, "pago",    "Cliente A", "desc", "2024-01-02"),
        ]
        with _patch_db(rows), _patch_settings():
            result = await detect_anomalies()
        # No high-value overdue either, so should be empty
        assert result == []

    async def test_zero_std_skips_zscore(self):
        """All values identical → std=0, z-score skipped."""
        rows = [
            ("txn_001", 500.0, "pago", "Cliente A", "desc", "2024-01-01"),
            ("txn_002", 500.0, "pago", "Cliente A", "desc", "2024-01-02"),
            ("txn_003", 500.0, "pago", "Cliente A", "desc", "2024-01-03"),
        ]
        with _patch_db(rows), _patch_settings():
            result = await detect_anomalies()
        assert result == []

    async def test_zscore_anomaly_detected(self):
        """One value far above the client mean → detected as anomaly."""
        rows = [
            ("txn_001",   100.0, "pago", "Cliente A", "desc", "2024-01-01"),
            ("txn_002",   110.0, "pago", "Cliente A", "desc", "2024-01-02"),
            ("txn_003",   105.0, "pago", "Cliente A", "desc", "2024-01-03"),
            ("txn_004",   108.0, "pago", "Cliente A", "desc", "2024-01-04"),
            ("txn_005", 10000.0, "pago", "Cliente A", "outlier", "2024-01-05"),
        ]
        with _patch_db(rows), _patch_settings():
            result = await detect_anomalies()
        anomaly_ids = [r["transacao_id"] for r in result]
        assert "txn_005" in anomaly_ids

    async def test_high_value_overdue_detected(self):
        """Overdue transaction above P75 → detected regardless of z-score."""
        rows = [
            ("txn_001", 100.0,  "pago",     "A", "desc", "2024-01-01"),
            ("txn_002", 200.0,  "pago",     "B", "desc", "2024-01-02"),
            ("txn_003", 300.0,  "pago",     "C", "desc", "2024-01-03"),
            ("txn_004", 900.0,  "atrasado", "D", "big overdue", "2024-01-04"),
        ]
        with _patch_db(rows), _patch_settings():
            result = await detect_anomalies()
        anomaly_ids = [r["transacao_id"] for r in result]
        assert "txn_004" in anomaly_ids

    async def test_low_value_overdue_not_flagged(self):
        """Overdue transaction below P75 → not flagged as high-value overdue."""
        rows = [
            ("txn_001", 1000.0, "pago",     "A", "desc", "2024-01-01"),
            ("txn_002", 2000.0, "pago",     "B", "desc", "2024-01-02"),
            ("txn_003", 3000.0, "pago",     "C", "desc", "2024-01-03"),
            ("txn_004",   10.0, "atrasado", "D", "small", "2024-01-04"),
        ]
        with _patch_db(rows), _patch_settings():
            result = await detect_anomalies()
        anomaly_ids = [r["transacao_id"] for r in result]
        assert "txn_004" not in anomaly_ids

    async def test_result_structure(self):
        """Each anomaly dict has transacao_id, motivo, score."""
        rows = [
            ("txn_001", 100.0,  "pago",     "A", "desc", "2024-01-01"),
            ("txn_002", 200.0,  "pago",     "B", "desc", "2024-01-02"),
            ("txn_003", 300.0,  "pago",     "C", "desc", "2024-01-03"),
            ("txn_004", 900.0,  "atrasado", "D", "big",  "2024-01-04"),
        ]
        with _patch_db(rows), _patch_settings():
            result = await detect_anomalies()
        for item in result:
            assert "transacao_id" in item
            assert "motivo" in item
            assert "score" in item

    async def test_score_bounded_between_0_and_1(self):
        """Anomaly scores must stay in [0, 1]."""
        rows = [
            ("txn_001",   100.0, "pago", "A", "desc", "2024-01-01"),
            ("txn_002",   105.0, "pago", "A", "desc", "2024-01-02"),
            ("txn_003",   102.0, "pago", "A", "desc", "2024-01-03"),
            ("txn_004", 99999.0, "pago", "A", "extreme", "2024-01-04"),
        ]
        with _patch_db(rows), _patch_settings():
            result = await detect_anomalies()
        for item in result:
            assert 0.0 <= item["score"] <= 1.0

    async def test_no_duplicate_ids(self):
        """Same transaction should not appear twice (z-score + overdue overlap)."""
        rows = [
            ("txn_001",   100.0, "pago",     "A", "desc", "2024-01-01"),
            ("txn_002",   102.0, "pago",     "A", "desc", "2024-01-02"),
            ("txn_003",   101.0, "pago",     "A", "desc", "2024-01-03"),
            ("txn_004", 50000.0, "atrasado", "A", "huge", "2024-01-04"),
        ]
        with _patch_db(rows), _patch_settings():
            result = await detect_anomalies()
        ids = [r["transacao_id"] for r in result]
        assert len(ids) == len(set(ids))

    async def test_no_api_key_returns_local_result(self):
        """With empty API key, falls back to local computation without LLM call."""
        rows = [
            ("txn_001", 100.0,  "pago",     "A", "desc", "2024-01-01"),
            ("txn_002", 200.0,  "pago",     "B", "desc", "2024-01-02"),
            ("txn_003", 300.0,  "pago",     "C", "desc", "2024-01-03"),
            ("txn_004", 900.0,  "atrasado", "D", "big",  "2024-01-04"),
        ]
        with _patch_db(rows), _patch_settings(api_key=""):
            result = await detect_anomalies()
        assert isinstance(result, list)
        assert all("transacao_id" in r for r in result)

    async def test_capped_at_ten_anomalies(self):
        """Even with many anomalies, only top 10 are returned."""
        import random
        random.seed(0)
        # 15 clients each with one big outlier
        rows = []
        for i in range(15):
            client = f"Client_{i}"
            for j in range(3):
                rows.append((f"txn_{i}_{j}", 100.0, "pago", client, "normal", "2024-01-01"))
            rows.append((f"txn_{i}_out", 99999.0, "pago", client, "outlier", "2024-01-02"))
        with _patch_db(rows), _patch_settings():
            result = await detect_anomalies()
        assert len(result) <= 10
