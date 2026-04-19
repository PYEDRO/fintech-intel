"""
Router de upload — modo assíncrono com BackgroundTasks.

POST /api/upload          → aceita o arquivo e retorna job_id imediatamente
GET  /api/upload/status/{job_id} → polling do progresso

O frontend faz polling a cada 1.5s até status='done' ou 'error'.
"""
import logging
from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from app.services.job_store import job_store
from app.services.ingestion import process_upload_background
from app.models.schemas import UploadJobResponse, UploadStatusResponse

router = APIRouter(prefix="/api", tags=["upload"])
logger = logging.getLogger(__name__)

_ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv"}


@router.post("/upload", response_model=UploadJobResponse)
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
) -> UploadJobResponse:
    """
    Recebe o arquivo, cria um job e inicia o processamento em background.
    Retorna imediatamente com o job_id para polling.
    """
    filename = file.filename or ""
    if not filename:
        raise HTTPException(status_code=400, detail="Nome de arquivo inválido.")

    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Formato não suportado: '{ext}'. Envie .xlsx, .xls ou .csv.",
        )

    # Lê os bytes AGORA, enquanto o contexto da request ainda está aberto.
    # Se ler dentro do background task, o UploadFile já estará fechado.
    try:
        contents = await file.read()
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Erro ao ler o arquivo: {exc}")

    if not contents:
        raise HTTPException(status_code=400, detail="Arquivo vazio.")

    # Cria o job no store
    job_id = await job_store.create()

    # Agenda o processamento — retorna imediatamente
    background_tasks.add_task(
        process_upload_background,
        contents=contents,
        filename=filename,
        job_id=job_id,
    )

    logger.info("Upload recebido: %s (%d bytes) → job_id=%s", filename, len(contents), job_id)

    return UploadJobResponse(
        job_id=job_id,
        status="queued",
        message=f"Arquivo '{filename}' aceito. Acompanhe o progresso via polling.",
    )


@router.get("/upload/status/{job_id}", response_model=UploadStatusResponse)
async def upload_status(job_id: str) -> UploadStatusResponse:
    """Retorna o estado atual do job de processamento."""
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail=f"Job '{job_id}' não encontrado. Pode ter expirado (TTL: 2h).",
        )
    return UploadStatusResponse(**job)
