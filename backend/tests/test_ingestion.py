"""Tests for ingestion pipeline — parsing, cleaning, SQLite persistence."""
import io
import pytest
import pandas as pd
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import UploadFile

from app.services.ingestion import _clean_dataframe, process_upload


# ── Helper ────────────────────────────────────────────────────────────────────

def make_df(n: int = 5) -> pd.DataFrame:
    return pd.DataFrame({
        "id": [f"txn_{i:05d}" for i in range(n)],
        "valor": [100.0 + i * 10 for i in range(n)],
        "data": ["2024-01-15"] * n,
        "status": ["pago", "pendente", "atrasado", "pago", "pago"][:n],
        "cliente": ["Empresa A"] * n,
        "descricao": [f"Descrição {i}" for i in range(n)],
    })


def make_xlsx_bytes(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def make_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode()


# ── _clean_dataframe ──────────────────────────────────────────────────────────

class TestCleanDataframe:
    def test_happy_path(self):
        df = make_df()
        result = _clean_dataframe(df)
        assert len(result) == 5
        assert set(result.columns) >= {"id", "valor", "data", "status", "cliente", "descricao", "categoria"}

    def test_missing_required_column_raises(self):
        df = make_df().drop(columns=["valor"])
        with pytest.raises(ValueError, match="Colunas ausentes"):
            _clean_dataframe(df)

    def test_drops_nan_rows(self):
        df = make_df()
        df.loc[2, "valor"] = None
        result = _clean_dataframe(df)
        assert len(result) == 4

    def test_status_normalized_to_lowercase(self):
        df = make_df()
        df["status"] = ["Pago", "PENDENTE", "Atrasado", "pago", "pendente"]
        result = _clean_dataframe(df)
        assert all(s in {"pago", "pendente", "atrasado"} for s in result["status"])

    def test_column_names_stripped(self):
        df = make_df()
        df.columns = [" id ", " valor ", " data ", " status ", " cliente ", " descricao "]
        result = _clean_dataframe(df)
        assert "id" in result.columns

    def test_data_formatted_as_iso(self):
        df = make_df()
        result = _clean_dataframe(df)
        assert result["data"].iloc[0] == "2024-01-15"

    def test_categoria_column_added_if_missing(self):
        df = make_df()
        assert "categoria" not in df.columns
        result = _clean_dataframe(df)
        assert "categoria" in result.columns


# ── process_upload ────────────────────────────────────────────────────────────

def _fake_get_db():
    """Return a context manager yielding an in-memory SQLite with the transacoes table."""
    import sqlite3
    from contextlib import contextmanager

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


@pytest.mark.asyncio
class TestProcessUpload:
    async def _make_upload(self, content: bytes, filename: str) -> UploadFile:
        mock = MagicMock(spec=UploadFile)
        mock.filename = filename
        mock.read = AsyncMock(return_value=content)
        return mock

    @patch("app.services.ingestion.classify_descriptions_batch", new_callable=AsyncMock)
    @patch("app.services.ingestion.build_faiss_index")
    @patch("app.services.ingestion.get_db")
    async def test_xlsx_upload_returns_summary(self, mock_db, mock_faiss, mock_classify):
        mock_classify.return_value = ["Assinatura Recorrente"] * 5
        mock_faiss.return_value = 5
        mock_db.side_effect = lambda: _fake_get_db()

        df = make_df()
        content = make_xlsx_bytes(df)
        upload = await self._make_upload(content, "test.xlsx")

        result = await process_upload(upload)

        assert result["total_rows"] == 5
        assert result["classified"] == 5
        assert result["indexed"] == 5
        assert "metrics_summary" in result

    @patch("app.services.ingestion.classify_descriptions_batch", new_callable=AsyncMock)
    @patch("app.services.ingestion.build_faiss_index")
    @patch("app.services.ingestion.get_db")
    async def test_csv_upload(self, mock_db, mock_faiss, mock_classify):
        mock_classify.return_value = ["Plano Premium"] * 5
        mock_faiss.return_value = 5
        mock_db.side_effect = lambda: _fake_get_db()

        df = make_df()
        content = make_csv_bytes(df)
        upload = await self._make_upload(content, "test.csv")

        result = await process_upload(upload)
        assert result["total_rows"] == 5

    async def test_invalid_extension_raises_400(self):
        from fastapi import HTTPException
        upload = await self._make_upload(b"dummy", "file.txt")
        with pytest.raises(HTTPException) as exc_info:
            await process_upload(upload)
        assert exc_info.value.status_code == 400
