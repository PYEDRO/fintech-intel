"""
Pipeline de ingestão de dados financeiros.

Suporta dois modos:
- process_upload(file)          → síncrono, para chamadas diretas (testes, compat)
- process_upload_background(...)→ assíncrono com job_store, para BackgroundTasks
"""
import io
import logging
import asyncio
from typing import Optional
import pandas as pd
from fastapi import UploadFile, HTTPException
from app.db import get_db
from app.services.classifier import classify_descriptions_batch
from app.services.rag import build_faiss_index

logger = logging.getLogger(__name__)


# ── Limpeza e normalização do DataFrame ───────────────────────────────────────

def _clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza colunas, tipos e descarta linhas inválidas."""
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

    status_map = {"paid": "pago", "pending": "pendente", "overdue": "atrasado"}
    df["status"] = df["status"].replace(status_map)

    if "categoria" not in df.columns:
        df["categoria"] = None

    return df.reset_index(drop=True)


# ── Pipeline interno (bytes → result dict) ─────────────────────────────────────

async def _run_pipeline(
    contents: bytes,
    filename: str,
    progress_cb=None,  # Callable[[int, str], Awaitable[None]] | None
) -> dict:
    """
    Executa o pipeline completo sobre bytes de arquivo.

    progress_cb(progress_pct, step_label) é chamado ao longo do processo
    para atualizar o job_store. Se None, opera silenciosamente.
    """

    async def _update(pct: int, step: str):
        if progress_cb:
            await progress_cb(pct, step)

    # ── 1. Parse ──────────────────────────────────────────────────────────────
    await _update(5, "Lendo arquivo...")
    buf = io.BytesIO(contents)
    try:
        if filename.endswith((".xlsx", ".xls")):
            df = pd.read_excel(buf)
        elif filename.endswith(".csv"):
            df = pd.read_csv(buf)
        else:
            raise ValueError("Formato não suportado. Envie .xlsx ou .csv")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Erro ao processar arquivo: {exc}") from exc

    # ── 2. Limpeza ────────────────────────────────────────────────────────────
    await _update(15, "Limpando e validando dados...")
    df = _clean_dataframe(df)
    total_rows = len(df)
    logger.info("Linhas após limpeza: %d", total_rows)

    # ── 3. Persist SQLite ─────────────────────────────────────────────────────
    await _update(25, "Salvando no banco de dados...")
    with get_db() as conn:
        conn.execute("DELETE FROM transacoes")
        df[["id", "valor", "data", "status", "cliente", "descricao", "categoria"]].to_sql(
            "transacoes", conn, if_exists="append", index=False
        )
    logger.info("Transações persistidas no SQLite.")

    # ── 4. Classificação LLM ──────────────────────────────────────────────────
    await _update(40, "Classificando transações com IA...")
    descriptions = df["descricao"].tolist()
    categories = await classify_descriptions_batch(descriptions)
    df["categoria"] = categories
    classified = sum(1 for c in categories if c != "Não Classificado")

    await _update(70, "Salvando categorias...")
    with get_db() as conn:
        for _, row in df.iterrows():
            conn.execute(
                "UPDATE transacoes SET categoria = ? WHERE id = ?",
                (row["categoria"], row["id"]),
            )
    logger.info("Categorias salvas: %d/%d", classified, total_rows)

    # ── 5. FAISS Indexing ─────────────────────────────────────────────────────
    await _update(80, "Indexando vetores semânticos...")
    indexed = build_faiss_index(df)
    logger.info("FAISS index construído: %d vetores.", indexed)

    # ── 6. Resumo ─────────────────────────────────────────────────────────────
    await _update(95, "Finalizando...")
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


# ── Função de background task (chamada por upload.py) ─────────────────────────

async def process_upload_background(
    contents: bytes,
    filename: str,
    job_id: str,
) -> None:
    """
    Executa o pipeline em background, atualizando o job_store ao longo do processo.
    Nunca propaga exceções — erros ficam registrados no job.
    """
    from app.services.job_store import job_store

    async def cb(pct: int, step: str):
        await job_store.update(job_id, status="processing", progress=pct, step=step)

    try:
        await job_store.update(job_id, status="processing", progress=1, step="Iniciando...")
        result = await _run_pipeline(contents, filename, progress_cb=cb)
        await job_store.update(
            job_id,
            status="done",
            progress=100,
            step="Processamento concluído!",
            result=result,
        )
        logger.info("Job %s concluído: %d linhas.", job_id, result["total_rows"])
    except Exception as exc:
        logger.exception("Job %s falhou: %s", job_id, exc)
        await job_store.update(
            job_id,
            status="error",
            progress=0,
            step="Erro no processamento.",
            error=str(exc),
        )


# ── Compatibilidade: mantém process_upload para uso direto (testes) ───────────

async def process_upload(file: UploadFile) -> dict:
    """API legada: aceita UploadFile diretamente (usada nos testes)."""
    filename = file.filename or ""
    if not filename:
        raise HTTPException(status_code=400, detail="Arquivo inválido")

    contents = await file.read()
    try:
        return await _run_pipeline(contents, filename, progress_cb=None)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("process_upload falhou: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
