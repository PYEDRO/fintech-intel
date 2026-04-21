"""Tests for RAG pipeline — embedding, indexing, retrieval."""
import json
import pytest
import numpy as np
import pandas as pd
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

from app.services.rag import _doc_text, build_faiss_index, retrieve, answer_question


# ── _doc_text ─────────────────────────────────────────────────────────────────

class TestDocText:
    def test_includes_all_fields(self):
        row = {
            "id": "txn_001",
            "cliente": "Empresa A",
            "valor": 1500.00,
            "data": "2024-03-01",
            "status": "pago",
            "categoria": "Assinatura Recorrente",
            "descricao": "Mensalidade plataforma",
        }
        text = _doc_text(row)
        assert "txn_001" in text
        assert "Empresa A" in text
        assert "1500.00" in text
        assert "Assinatura Recorrente" in text
        assert "Mensalidade plataforma" in text

    def test_missing_categoria_shows_na(self):
        row = {"id": "x", "cliente": "A", "valor": 100.0, "data": "2024-01-01", "status": "pago", "descricao": "test"}
        text = _doc_text(row)
        assert "N/A" in text


# ── build_faiss_index ─────────────────────────────────────────────────────────

def make_test_df(n: int = 10) -> pd.DataFrame:
    return pd.DataFrame({
        "id": [f"txn_{i:03d}" for i in range(n)],
        "valor": [float(i * 100) for i in range(n)],
        "data": ["2024-01-01"] * n,
        "status": ["pago"] * n,
        "cliente": ["Empresa A"] * n,
        "descricao": [
            "Contratação de serviço premium",
            "Assinatura recorrente mensal",
            "Licença anual de software",
            "Compra avulsa de produto",
            "Renovação de plano",
            "Serviço de suporte técnico",
            "Consultoria especializada",
            "Treinamento corporativo",
            "Manutenção de sistema",
            "Implementação de projeto",
        ][:n],
        "categoria": ["Assinatura Recorrente"] * n,
    })


class TestBuildFaissIndex:
    def test_returns_correct_count(self, tmp_path):
        df = make_test_df(5)
        with (
            patch("app.services.rag.settings") as mock_settings,
        ):
            mock_settings.embedding_model = "all-MiniLM-L6-v2"
            mock_settings.embedding_dim = 384
            mock_settings.faiss_index_path = str(tmp_path / "faiss.index")
            mock_settings.faiss_meta_path = str(tmp_path / "meta.json")
            # Reload module-level singletons
            import app.services.rag as rag_module
            rag_module._model = None
            rag_module._index = None
            rag_module._meta = None

            n = build_faiss_index(df)
            assert n == 5

    def test_meta_file_persisted(self, tmp_path):
        df = make_test_df(3)
        with patch("app.services.rag.settings") as mock_settings:
            mock_settings.embedding_model = "all-MiniLM-L6-v2"
            mock_settings.embedding_dim = 384
            mock_settings.faiss_index_path = str(tmp_path / "faiss.index")
            mock_settings.faiss_meta_path = str(tmp_path / "meta.json")
            import app.services.rag as rag_module
            rag_module._model = None
            rag_module._index = None
            rag_module._meta = None

            build_faiss_index(df)
            meta_path = Path(mock_settings.faiss_meta_path)
            assert meta_path.exists()
            with open(meta_path) as f:
                meta = json.load(f)
            assert len(meta) == 3
            assert meta[0]["id"] == "txn_000"


# ── retrieve ──────────────────────────────────────────────────────────────────

class TestRetrieve:
    def _setup_index(self, tmp_path) -> None:
        """Build a real index with known docs."""
        import app.services.rag as rag_module
        rag_module._model = None
        rag_module._index = None
        rag_module._meta = None

        df = make_test_df(10)
        with patch("app.services.rag.settings") as mock_settings:
            mock_settings.embedding_model = "all-MiniLM-L6-v2"
            mock_settings.embedding_dim = 384
            mock_settings.faiss_index_path = str(tmp_path / "faiss.index")
            mock_settings.faiss_meta_path = str(tmp_path / "meta.json")
            build_faiss_index(df)
            return mock_settings.faiss_index_path, mock_settings.faiss_meta_path

    def test_returns_top_k_results(self, tmp_path):
        import app.services.rag as rag_module
        rag_module._model = None
        rag_module._index = None
        rag_module._meta = None

        df = make_test_df(10)
        with patch("app.services.rag.settings") as mock_settings:
            mock_settings.embedding_model = "all-MiniLM-L6-v2"
            mock_settings.embedding_dim = 384
            mock_settings.faiss_index_path = str(tmp_path / "faiss.index")
            mock_settings.faiss_meta_path = str(tmp_path / "meta.json")
            mock_settings.rag_top_k = 3
            build_faiss_index(df)

            results = retrieve("contratação de serviço", k=3)
            assert len(results) == 3
            assert all("id" in r for r in results)
            assert all("_score" in r for r in results)

    def test_semantic_relevance(self, tmp_path):
        """'assinatura recorrente' query should rank subscription docs higher."""
        import app.services.rag as rag_module
        rag_module._model = None
        rag_module._index = None
        rag_module._meta = None

        df = make_test_df(10)
        with patch("app.services.rag.settings") as mock_settings:
            mock_settings.embedding_model = "all-MiniLM-L6-v2"
            mock_settings.embedding_dim = 384
            mock_settings.faiss_index_path = str(tmp_path / "faiss.index")
            mock_settings.faiss_meta_path = str(tmp_path / "meta.json")
            mock_settings.rag_top_k = 5
            build_faiss_index(df)

            results = retrieve("assinatura recorrente mensal", k=5)
            top_descriptions = [r["descricao"] for r in results[:2]]
            assert any("recorrente" in d.lower() or "assinatura" in d.lower() for d in top_descriptions)


# ── answer_question ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestAnswerQuestion:
    async def test_no_api_key_returns_fallback(self, tmp_path):
        """Pergunta específica (não-agregada) → vai para FAISS + rule-based quando sem API key."""
        import app.services.rag as rag_module
        from contextlib import contextmanager

        rag_module._model = None
        rag_module._index = None
        rag_module._meta = None

        # Mock get_db para a query COUNT(*) feita no ramo semântico
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = [5]

        @contextmanager
        def fake_get_db():
            yield mock_conn

        df = make_test_df(5)
        with (
            patch("app.services.rag.settings") as mock_settings,
            patch("app.services.rag.get_db", fake_get_db),
        ):
            mock_settings.embedding_model = "all-MiniLM-L6-v2"
            mock_settings.embedding_dim = 384
            mock_settings.faiss_index_path = str(tmp_path / "faiss.index")
            mock_settings.faiss_meta_path = str(tmp_path / "meta.json")
            mock_settings.rag_top_k = 5
            mock_settings.deepseek_api_key = ""  # no key → rule-based fallback
            mock_settings.deepseek_base_url = "https://api.deepseek.com"
            mock_settings.deepseek_model = "deepseek-chat"

            build_faiss_index(df)
            # Pergunta específica (não agrega totais) → usa FAISS path
            result = await answer_question("qual o detalhe da contratação de serviço premium?")

        assert "answer" in result
        assert "sources" in result
        assert isinstance(result["sources"], list)

    async def test_aggregate_intent_uses_db_directly(self, tmp_path):
        """Pergunta de agregação → usa get_db diretamente sem precisar de FAISS ou API key."""
        import app.services.rag as rag_module
        from contextlib import contextmanager

        rag_module._model = None
        rag_module._index = None
        rag_module._meta = None

        # Simula banco com 1 transação atrasada
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        summary_row = MagicMock()
        summary_row.__getitem__ = lambda self, k: {"cnt": 1, "soma": 500.0}[k]
        top_row = MagicMock()
        top_row.__iter__ = MagicMock(return_value=iter([]))
        mock_conn.execute.return_value.fetchone.return_value = summary_row
        mock_conn.execute.return_value.fetchall.return_value = []

        @contextmanager
        def fake_get_db():
            yield mock_conn

        with patch("app.services.rag.get_db", fake_get_db):
            result = await answer_question("quais transações estão atrasadas?")

        assert "answer" in result
        assert "sources" in result
