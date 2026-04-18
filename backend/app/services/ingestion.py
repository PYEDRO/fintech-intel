import io
import logging
from typing import Optional
import pandas as pd
from fastapi import UploadFile, HTTPException
from app.db import get_db
from app.config import settings
from app.services.classifier import classify_descriptions_batch
from app.services.rag import build_faiss_index
from app.services.job_store import JobStatus, PIPELINE_STEPS, update_job
from app.repositories.transaction_repository import TransactionRepository

logger = logging.getLogger(__name__)


def _clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize column names, cast types, drop nulls on required fields."""
    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]

    required = {"id", "valor", "data", "status", "cliente", "descricao"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Colunas ausentes no arquivo: {missing}")

    df["data"] = pd.to_datetime(df["data"], dayfirst=False, errors="coerce")
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    df = df.dropna(subset=["id", "valor", "data", "status", "cliente", "descricao"]).copy()

    df["id"] = df["id"].astype(str).str.strip()
    df["status"] = df["status"].str.strip().str.lower()
    df["cliente"] = df["cliente"].str.strip()
    df["descricao"] = df["descricao"].str.strip()
    df["data"] = df["data"].dt.strftime("%Y-%m-%d")

    status_map = {"paid": "pago", "pending": "pendente", "overdue": "atrasado"}
    df["status"] = df["status"].replace(status_map)

    if "categoria" not in df.columns:
        df["categoria"] = None

    return df.reset_index(drop=True)


async def _read_file(content: bytes, filename: str) -> pd.DataFrame:
    """Parse bytes into DataFrame based on file extension."""
    buf = io.BytesIO(content)
    if filename.endswith((".xlsx", ".xls")):
        return pd.read_excel(buf)
    elif filename.endswith(".csv"):
        return pd.read_csv(buf)
    raise HTTPException(status_code=400, detail="Formato não suportado. Envie .xlsx ou .csv")


async def run_pipeline(content: bytes, filename: str, job_id: Optional[str] = None) -> dict:
    """
    Full ingestion pipeline:
      1. Read + clean (Pandas)
      2. Persist to SQLite (via TransactionRepository)
      3. LLM classify in batches of 20
      4. Build FAISS index (fastembed ONNX)
      5. Return metrics summary

    job_id: if provided, publishes SSE-ready progress via job_store.
    """

    def _progress(step_index: int, label: str, status: JobStatus = JobStatus.PROCESSING) -> None:
        if job_id:
            update_job(job_id, step_index=step_index, step_label=label, status=status)
        logger.info("[%s] %s", step_index, label)

    # ── Step 1: Read + clean ──────────────────────────────────────────────────
    _progress(1, PIPELINE_STEPS[0])
    try:
        raw_df = await _read_file(content, filename)
    except HTTPException:
        if job_id:
            update_job(job_id, status=JobStatus.FAILED, error="Formato inválido")
        raise
    try:
        df = _clean_dataframe(raw_df)
    except ValueError as exc:
        if job_id:
            update_job(job_id, status=JobStatus.FAILED, error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc))

    total_rows = len(df)
    logger.info("Linhas lidas após limpeza: %d", total_rows)

    # ── Step 2: Persist to SQLite ─────────────────────────────────────────────
    _progress(2, PIPELINE_STEPS[1])
    with get_db() as conn:
        repo = TransactionRepository(conn)
        repo.replace_all(df)

    # ── Step 3: LLM Classification ────────────────────────────────────────────
    _progress(3, PIPELINE_STEPS[2])
    descriptions = df["descricao"].tolist()
    categories = await classify_descriptions_batch(descriptions)
    df = df.copy()
    df["categoria"] = categories
    classified = sum(1 for c in categories if c != "Não Classificado")

    with get_db() as conn:
        repo = TransactionRepository(conn)
        for _, row in df.iterrows():
            repo.update_category(row["id"], row["categoria"])

    logger.info("Categorias salvas: %d/%d", classified, total_rows)

    # ── Step 4: FAISS Indexing ────────────────────────────────────────────────
    _progress(4, PIPELINE_STEPS[3])
    indexed = build_faiss_index(df)
    logger.info("FAISS index construído: %d vetores", indexed)

    # ── Step 5: Done ──────────────────────────────────────────────────────────
    metrics_summary = {
        "receita_total": round(float(df[df["status"] == "pago"]["valor"].sum()), 2),
        "total_transacoes": total_rows,
        "status_breakdown": df["status"].value_counts().to_dict(),
        "clientes": int(df["cliente"].nunique()),
    }
    result = {
        "total_rows": total_rows,
        "classified": classified,
        "indexed": indexed,
        "metrics_summary": metrics_summary,
    }
    _progress(5, PIPELINE_STEPS[4], status=JobStatus.COMPLETED)
    if job_id:
        update_job(job_id, result=result)
    return result


# Kept for sync use in tests
async def process_upload(file: UploadFile) -> dict:
    """Thin wrapper for direct (non-background) use."""
    filename = file.filename or ""
    content = await file.read()
    return await run_pipeline(content, filename)
