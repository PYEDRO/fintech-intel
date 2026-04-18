import io
import logging
import asyncio
from typing import Optional
import pandas as pd
from fastapi import UploadFile, HTTPException
from app.db import get_db
from app.config import settings
from app.services.classifier import classify_descriptions_batch
from app.services.rag import build_faiss_index

logger = logging.getLogger(__name__)


def _clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize column names, cast types, drop nulls on required fields."""
    df.columns = [c.strip().lower() for c in df.columns]

    required = {"id", "valor", "data", "status", "cliente", "descricao"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Colunas ausentes no arquivo: {missing}")

    df["data"] = pd.to_datetime(df["data"], dayfirst=True, errors="coerce")
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    df = df.dropna(subset=["id", "valor", "data", "status", "cliente", "descricao"]).copy()

    df["id"] = df["id"].astype(str).str.strip()
    df["status"] = df["status"].str.strip().str.lower()
    df["cliente"] = df["cliente"].str.strip()
    df["descricao"] = df["descricao"].str.strip()
    df["data"] = df["data"].dt.strftime("%Y-%m-%d")

    # Normalize status variants
    status_map = {"paid": "pago", "pending": "pendente", "overdue": "atrasado"}
    df["status"] = df["status"].replace(status_map)

    if "categoria" not in df.columns:
        df["categoria"] = None

    return df.reset_index(drop=True)


async def process_upload(file: UploadFile) -> dict:
    """Full ingestion pipeline: read → clean → persist → classify → embed."""
    filename = file.filename or ""
    contents = await file.read()
    buf = io.BytesIO(contents)

    try:
        if filename.endswith(".xlsx") or filename.endswith(".xls"):
            df = pd.read_excel(buf)
        elif filename.endswith(".csv"):
            df = pd.read_csv(buf)
        else:
            raise HTTPException(status_code=400, detail="Formato não suportado. Envie .xlsx ou .csv")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Falha ao ler arquivo: %s", exc)
        raise HTTPException(status_code=422, detail=f"Erro ao processar arquivo: {exc}")

    try:
        df = _clean_dataframe(df)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    total_rows = len(df)
    logger.info("Linhas lidas após limpeza: %d", total_rows)

    # ── Persist raw to SQLite ─────────────────────────────────────────────────
    with get_db() as conn:
        conn.execute("DELETE FROM transacoes")
        df[["id", "valor", "data", "status", "cliente", "descricao", "categoria"]].to_sql(
            "transacoes", conn, if_exists="append", index=False
        )
    logger.info("Transações persistidas no SQLite")

    # ── LLM Classification (batches of 20) ────────────────────────────────────
    descriptions = df["descricao"].tolist()
    categories = await classify_descriptions_batch(descriptions)
    df["categoria"] = categories
    classified = sum(1 for c in categories if c != "Não Classificado")

    with get_db() as conn:
        for _, row in df.iterrows():
            conn.execute(
                "UPDATE transacoes SET categoria = ? WHERE id = ?",
                (row["categoria"], row["id"]),
            )
    logger.info("Categorias salvas: %d/%d", classified, total_rows)

    # ── FAISS Indexing ────────────────────────────────────────────────────────
    indexed = build_faiss_index(df)
    logger.info("FAISS index construído: %d vetores", indexed)

    # ── Quick metrics summary ─────────────────────────────────────────────────
    metrics_summary = {
        "receita_total": round(df[df["status"] == "pago"]["valor"].sum(), 2),
        "total_transacoes": total_rows,
        "status_breakdown": df["status"].value_counts().to_dict(),
        "clientes": df["cliente"].nunique(),
    }

    return {
        "total_rows": total_rows,
        "classified": classified,
        "indexed": indexed,
        "metrics_summary": metrics_summary,
    }
