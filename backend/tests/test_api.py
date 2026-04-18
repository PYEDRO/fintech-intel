"""Integration tests for all API endpoints using FastAPI TestClient."""
import sqlite3
import pytest
from contextlib import contextmanager
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from app.main import app


SAMPLE_ROWS = [
    ("txn_001", 1000.0, "2024-01-10", "pago",     "Empresa A", "desc A", "Assinatura Recorrente"),
    ("txn_002", 2000.0, "2024-01-15", "pago",     "Empresa A", "desc B", "Plano Premium"),
    ("txn_003",  500.0, "2024-02-05", "pendente", "Startup X", "desc C", "Serviço Avulso"),
    ("txn_004", 1500.0, "2024-02-20", "atrasado", "Loja Y",    "desc D", "Compra Única"),
    ("txn_005",  750.0, "2024-03-01", "pago",     "Startup X", "desc E", "Assinatura Recorrente"),
]


def _make_db(rows=SAMPLE_ROWS):
    @contextmanager
    def _ctx():
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
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    return _ctx()


@pytest.fixture(scope="module")
def client():
    with patch("app.main.init_db"):
        with TestClient(app) as c:
            yield c


# ── /health ───────────────────────────────────────────────────────────────────

class TestHealth:
    def test_returns_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_has_version(self, client):
        assert "version" in client.get("/health").json()


# ── /api/transactions ─────────────────────────────────────────────────────────

class TestTransactionsEndpoint:
    def _patch(self, rows=SAMPLE_ROWS):
        return patch("app.routers.transactions.get_db", side_effect=lambda: _make_db(rows))

    def test_empty_db(self, client):
        with self._patch([]):
            r = client.get("/api/transactions")
        assert r.status_code == 200
        data = r.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["pages"] == 1

    def test_returns_all_items(self, client):
        with self._patch():
            r = client.get("/api/transactions?per_page=10")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 5
        assert len(data["items"]) == 5

    def test_pagination_limits_results(self, client):
        with self._patch():
            r = client.get("/api/transactions?page=1&per_page=2")
        assert r.status_code == 200
        data = r.json()
        assert len(data["items"]) == 2
        assert data["pages"] == 3

    def test_filter_by_status(self, client):
        with self._patch():
            r = client.get("/api/transactions?status=pago")
        assert r.status_code == 200
        assert r.json()["total"] == 3

    def test_filter_by_cliente(self, client):
        with self._patch():
            r = client.get("/api/transactions?cliente=Empresa+A")
        assert r.status_code == 200
        assert r.json()["total"] == 2

    def test_search_filter(self, client):
        with self._patch():
            r = client.get("/api/transactions?search=desc+A")
        assert r.status_code == 200
        assert r.json()["total"] == 1

    def test_date_range_filter(self, client):
        with self._patch():
            r = client.get("/api/transactions?start_date=2024-02-01&end_date=2024-02-28")
        assert r.status_code == 200
        assert r.json()["total"] == 2

    def test_sort_ascending(self, client):
        with self._patch():
            r = client.get("/api/transactions?sort_by=valor&sort_order=asc")
        assert r.status_code == 200
        values = [item["valor"] for item in r.json()["items"]]
        assert values == sorted(values)

    def test_item_fields_present(self, client):
        with self._patch():
            r = client.get("/api/transactions?per_page=1")
        item = r.json()["items"][0]
        assert all(k in item for k in ["id", "valor", "data", "status", "cliente", "descricao"])


# ── /api/metrics ──────────────────────────────────────────────────────────────

class TestMetricsEndpoint:
    def _patch(self, rows=SAMPLE_ROWS):
        return patch("app.services.metrics_engine.get_db", side_effect=lambda: _make_db(rows))

    def test_returns_correct_totals(self, client):
        with self._patch():
            r = client.get("/api/metrics")
        assert r.status_code == 200
        data = r.json()
        assert data["receita_total"] == 3750.0
        assert data["total_transacoes"] == 5
        assert data["transacoes_pagas"] == 3
        assert data["transacoes_pendentes"] == 1
        assert data["transacoes_atrasadas"] == 1

    def test_empty_db_returns_zeros(self, client):
        with self._patch([]):
            r = client.get("/api/metrics")
        assert r.status_code == 200
        data = r.json()
        assert data["receita_total"] == 0.0
        assert data["total_transacoes"] == 0
        assert data["transacoes_pagas"] == 0

    def test_date_filter(self, client):
        with self._patch():
            r = client.get("/api/metrics?start_date=2024-01-01&end_date=2024-01-31")
        assert r.status_code == 200
        assert r.json()["total_transacoes"] == 2

    def test_cliente_filter(self, client):
        with self._patch():
            r = client.get("/api/metrics?cliente=Empresa+A")
        assert r.status_code == 200
        assert r.json()["total_transacoes"] == 2

    def test_response_has_all_fields(self, client):
        with self._patch():
            r = client.get("/api/metrics")
        data = r.json()
        for field in ["receita_total", "ticket_medio", "taxa_inadimplencia",
                      "evolucao_mensal", "por_cliente", "por_categoria", "por_status"]:
            assert field in data


# ── /api/insights ─────────────────────────────────────────────────────────────

class TestInsightsEndpoint:
    _MOCK_RESULT = {
        "insights": [
            {"titulo": "Receita OK", "descricao": "Desc", "tipo": "tendencia", "severidade": "baixa"}
        ],
        "anomalias": [],
        "score_clientes": [
            {"cliente": "Empresa A", "score": 8.5, "risco": "baixo", "motivo": "OK"}
        ],
    }

    def test_returns_insights_structure(self, client):
        with patch("app.routers.insights.generate_insights", new_callable=AsyncMock) as m:
            m.return_value = self._MOCK_RESULT
            r = client.get("/api/insights")
        assert r.status_code == 200
        data = r.json()
        assert "insights" in data
        assert "anomalias" in data
        assert "score_clientes" in data

    def test_insight_fields(self, client):
        with patch("app.routers.insights.generate_insights", new_callable=AsyncMock) as m:
            m.return_value = self._MOCK_RESULT
            r = client.get("/api/insights")
        insight = r.json()["insights"][0]
        assert all(k in insight for k in ["titulo", "descricao", "tipo", "severidade"])

    def test_404_on_file_not_found(self, client):
        with patch("app.routers.insights.generate_insights", new_callable=AsyncMock) as m:
            m.side_effect = FileNotFoundError("no index")
            r = client.get("/api/insights")
        assert r.status_code == 404

    def test_500_on_unexpected_error(self, client):
        with patch("app.routers.insights.generate_insights", new_callable=AsyncMock) as m:
            m.side_effect = RuntimeError("boom")
            r = client.get("/api/insights")
        assert r.status_code == 500


# ── /api/chat ─────────────────────────────────────────────────────────────────

class TestChatEndpoint:
    _MOCK_ANSWER = {
        "answer": "Encontrei 3 transações atrasadas.",
        "sources": [{"id": "txn_004", "descricao": "desc D", "relevance": 0.95}],
    }

    def test_returns_answer_and_sources(self, client):
        with patch("app.routers.chat.answer_question", new_callable=AsyncMock) as m:
            m.return_value = self._MOCK_ANSWER
            r = client.post("/api/chat", json={"question": "Transações atrasadas?"})
        assert r.status_code == 200
        data = r.json()
        assert "answer" in data
        assert "sources" in data

    def test_404_when_no_index(self, client):
        with patch("app.routers.chat.answer_question", new_callable=AsyncMock) as m:
            m.side_effect = FileNotFoundError("no index")
            r = client.post("/api/chat", json={"question": "Algo?"})
        assert r.status_code == 404

    def test_500_on_error(self, client):
        with patch("app.routers.chat.answer_question", new_callable=AsyncMock) as m:
            m.side_effect = RuntimeError("crash")
            r = client.post("/api/chat", json={"question": "Algo?"})
        assert r.status_code == 500


# ── /api/upload ───────────────────────────────────────────────────────────────

class TestUploadEndpoint:
    _MOCK_RESULT = {
        "total_rows": 10,
        "classified": 10,
        "indexed": 10,
        "metrics_summary": {"receita_total": 5000.0, "total_transacoes": 10,
                            "status_breakdown": {}, "clientes": 2},
    }

    def test_upload_returns_summary(self, client):
        with patch("app.routers.upload.process_upload", new_callable=AsyncMock) as m:
            m.return_value = self._MOCK_RESULT
            r = client.post(
                "/api/upload",
                files={"file": ("data.csv", b"id,valor\n1,100", "text/csv")},
            )
        assert r.status_code == 200
        data = r.json()
        assert data["total_rows"] == 10
        assert data["classified"] == 10

    def test_missing_filename_returns_400(self, client):
        with patch("app.routers.upload.process_upload", new_callable=AsyncMock):
            r = client.post(
                "/api/upload",
                files={"file": ("", b"", "application/octet-stream")},
            )
        assert r.status_code == 400
