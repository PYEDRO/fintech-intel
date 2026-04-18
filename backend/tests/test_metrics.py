"""Tests for metrics engine — KPI correctness, filter logic, and Holt projection."""
import pytest
import sqlite3
from unittest.mock import patch, MagicMock

from app.services.metrics_engine import get_metrics, _build_where, _holt_projection
from app.repositories.transaction_repository import TransactionRepository


# ── Helpers ───────────────────────────────────────────────────────────────────

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
        assert where == "" and params == []

    def test_start_date_only(self):
        where, params = _build_where("2024-01-01", None, None)
        assert "data >=" in where and params == ["2024-01-01"]

    def test_all_filters(self):
        where, params = _build_where("2024-01-01", "2024-12-31", "Empresa A")
        assert len(params) == 3


# ── _holt_projection ──────────────────────────────────────────────────────────

class TestHoltProjection:
    def test_returns_3_steps_by_default(self):
        data = [10000.0, 11000.0, 12000.0, 13000.0, 14000.0, 15000.0]
        proj = _holt_projection(data)
        assert len(proj) == 3

    def test_values_are_positive(self):
        data = [5000.0, 6000.0, 7000.0, 8000.0]
        proj = _holt_projection(data)
        assert all(v >= 0 for v in proj)

    def test_upward_trend_projects_higher(self):
        data = [1000.0, 2000.0, 3000.0, 4000.0, 5000.0, 6000.0]
        proj = _holt_projection(data)
        assert proj[0] > data[-1] * 0.8  # projection should be near or above last value

    def test_too_few_points_returns_empty(self):
        assert _holt_projection([5000.0]) == []

    def test_custom_steps(self):
        data = [100.0, 200.0, 300.0]
        assert len(_holt_projection(data, steps=6)) == 6


# ── TransactionRepository ─────────────────────────────────────────────────────

class TestTransactionRepository:
    def _make_repo(self, rows=SAMPLE_ROWS):
        conn = _create_test_db(rows)
        return TransactionRepository(conn), conn

    def test_count(self):
        repo, _ = self._make_repo()
        assert repo.count() == 5

    def test_get_aggregates(self):
        repo, _ = self._make_repo()
        agg = repo.get_aggregates()
        assert agg["total_transacoes"] == 5
        assert agg["pagas"] == 3
        assert agg["pendentes"] == 1
        assert agg["atrasadas"] == 1

    def test_get_aggregates_with_filter(self):
        repo, _ = self._make_repo()
        agg = repo.get_aggregates("WHERE cliente = ?", ["Empresa A"])
        assert agg["total_transacoes"] == 2

    def test_get_top_by_value(self):
        repo, _ = self._make_repo()
        top = repo.get_top_by_value(limit=2)
        assert top[0]["valor"] >= top[1]["valor"]

    def test_get_stats_by_client(self):
        repo, _ = self._make_repo()
        stats = repo.get_stats_by_client()
        clientes = [s["cliente"] for s in stats]
        assert "Empresa A" in clientes

    def test_get_monthly_evolution_ordered(self):
        repo, _ = self._make_repo()
        months = [r["mes"] for r in repo.get_monthly_evolution()]
        assert months == sorted(months)

    def test_list_paginated_limit(self):
        repo, _ = self._make_repo()
        rows, total = repo.list_paginated(limit=2, offset=0)
        assert len(rows) == 2
        assert total == 5

    def test_list_paginated_offset(self):
        repo, _ = self._make_repo()
        rows, _ = repo.list_paginated(limit=2, offset=4)
        assert len(rows) == 1


# ── get_metrics ───────────────────────────────────────────────────────────────

class TestGetMetrics:
    def test_receita_total_only_paid(self):
        conn = _create_test_db()
        with _patch_db(conn):
            m = get_metrics()
        assert m["receita_total"] == 3750.0  # 1000+2000+750

    def test_total_transacoes(self):
        conn = _create_test_db()
        with _patch_db(conn):
            m = get_metrics()
        assert m["total_transacoes"] == 5

    def test_taxa_inadimplencia(self):
        conn = _create_test_db()
        with _patch_db(conn):
            m = get_metrics()
        assert m["taxa_inadimplencia"] == 20.0  # 1/5

    def test_ticket_medio_only_paid(self):
        conn = _create_test_db()
        with _patch_db(conn):
            m = get_metrics()
        assert m["ticket_medio"] == 1250.0  # (1000+2000+750)/3

    def test_status_breakdown(self):
        conn = _create_test_db()
        with _patch_db(conn):
            m = get_metrics()
        assert m["transacoes_pagas"] == 3
        assert m["transacoes_pendentes"] == 1
        assert m["transacoes_atrasadas"] == 1

    def test_evolucao_mensal_ordered(self):
        conn = _create_test_db()
        with _patch_db(conn):
            m = get_metrics()
        months = [e["mes"] for e in m["evolucao_mensal"]]
        assert months == sorted(months)

    def test_filter_by_cliente(self):
        conn = _create_test_db()
        with _patch_db(conn):
            m = get_metrics(cliente="Empresa A")
        assert m["total_transacoes"] == 2

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
        assert m["taxa_inadimplencia"] == 0.0
