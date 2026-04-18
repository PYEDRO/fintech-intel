"""Tests for the metrics engine — KPI correctness and filter logic."""
import pytest
import sqlite3
from unittest.mock import patch, MagicMock

from app.services.metrics_engine import get_metrics, _build_where


# ── Helper: inject test data ──────────────────────────────────────────────────

SAMPLE_ROWS = [
    ("txn_001", 1000.0, "2024-01-10", "pago",     "Empresa A", "desc A", "Assinatura Recorrente"),
    ("txn_002", 2000.0, "2024-01-15", "pago",     "Empresa A", "desc B", "Plano Premium"),
    ("txn_003",  500.0, "2024-02-05", "pendente", "Startup X", "desc C", "Serviço Avulso"),
    ("txn_004", 1500.0, "2024-02-20", "atrasado", "Loja Y",    "desc D", "Compra Única"),
    ("txn_005",  750.0, "2024-03-01", "pago",     "Startup X", "desc E", "Assinatura Recorrente"),
]


def _create_test_db(rows=SAMPLE_ROWS) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE transacoes (
            id TEXT, valor REAL, data TEXT, status TEXT,
            cliente TEXT, descricao TEXT, categoria TEXT
        )
    """)
    conn.executemany("INSERT INTO transacoes VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    return conn


def _patch_db(conn: sqlite3.Connection):
    """Context manager to monkey-patch get_db with an in-memory connection."""
    from contextlib import contextmanager

    @contextmanager
    def fake_db():
        yield conn
        conn.commit()

    return patch("app.services.metrics_engine.get_db", fake_db)


# ── _build_where ──────────────────────────────────────────────────────────────

class TestBuildWhere:
    def test_empty(self):
        where, params = _build_where(None, None, None)
        assert where == ""
        assert params == []

    def test_start_date_only(self):
        where, params = _build_where("2024-01-01", None, None)
        assert "data >=" in where
        assert params == ["2024-01-01"]

    def test_all_filters(self):
        where, params = _build_where("2024-01-01", "2024-12-31", "Empresa A")
        assert "data >=" in where
        assert "data <=" in where
        assert "cliente" in where
        assert len(params) == 3


# ── get_metrics ───────────────────────────────────────────────────────────────

class TestGetMetrics:
    def test_receita_total_only_paid(self):
        conn = _create_test_db()
        with _patch_db(conn):
            m = get_metrics()
        # paid: 1000 + 2000 + 750 = 3750
        assert m["receita_total"] == 3750.0

    def test_total_transacoes(self):
        conn = _create_test_db()
        with _patch_db(conn):
            m = get_metrics()
        assert m["total_transacoes"] == 5

    def test_status_breakdown(self):
        conn = _create_test_db()
        with _patch_db(conn):
            m = get_metrics()
        assert m["transacoes_pagas"] == 3
        assert m["transacoes_pendentes"] == 1
        assert m["transacoes_atrasadas"] == 1

    def test_taxa_inadimplencia(self):
        conn = _create_test_db()
        with _patch_db(conn):
            m = get_metrics()
        # 1 atrasada / 5 total = 20%
        assert m["taxa_inadimplencia"] == 20.0

    def test_ticket_medio_only_paid(self):
        conn = _create_test_db()
        with _patch_db(conn):
            m = get_metrics()
        # (1000 + 2000 + 750) / 3 = 1250
        assert m["ticket_medio"] == 1250.0

    def test_evolucao_mensal_ordered(self):
        conn = _create_test_db()
        with _patch_db(conn):
            m = get_metrics()
        months = [e["mes"] for e in m["evolucao_mensal"]]
        assert months == sorted(months)

    def test_por_cliente_sorted_by_receita(self):
        conn = _create_test_db()
        with _patch_db(conn):
            m = get_metrics()
        receitas = [c["receita"] for c in m["por_cliente"]]
        assert receitas == sorted(receitas, reverse=True)

    def test_filter_by_cliente(self):
        conn = _create_test_db()
        with _patch_db(conn):
            m = get_metrics(cliente="Empresa A")
        assert m["total_transacoes"] == 2
        assert m["receita_total"] == 3000.0

    def test_filter_by_date_range(self):
        conn = _create_test_db()
        with _patch_db(conn):
            m = get_metrics(start_date="2024-02-01", end_date="2024-02-28")
        assert m["total_transacoes"] == 2

    def test_empty_database(self):
        conn = _create_test_db([])
        with _patch_db(conn):
            m = get_metrics()
        assert m["receita_total"] == 0.0
        assert m["total_transacoes"] == 0
        assert m["taxa_inadimplencia"] == 0.0
