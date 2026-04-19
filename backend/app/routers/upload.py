import logging

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.models.schemas import UploadResponse
from app.services.ingestion import process_upload

router = APIRouter(prefix="/api", tags=["upload"])
logger = logging.getLogger(__name__)


@router.post("/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile = File(...)) -> UploadResponse:
    """Receive XLSX/CSV, run ingestion pipeline and return summary."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Arquivo inválido")

    result = await process_upload(file)
    return UploadResponse(**result)
