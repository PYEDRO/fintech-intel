import asyncio
import json
import logging
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from app.services.ingestion import run_pipeline
from app.services.job_store import JobStatus, create_job, get_job, update_job

router = APIRouter(prefix="/api", tags=["upload"])
logger = logging.getLogger(__name__)


async def _background_pipeline(job_id: str, content: bytes, filename: str) -> None:
    """Wrapper so exceptions are caught and stored in the job store."""
    try:
        await run_pipeline(content, filename, job_id=job_id)
    except Exception as exc:
        logger.exception("Pipeline falhou para job %s", job_id)
        update_job(job_id, status=JobStatus.FAILED, error=str(exc))


@router.post("/upload")
async def upload_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
) -> dict:
    """
    Receive file, start background pipeline, return job_id immediately.
    Frontend polls /api/upload/progress/{job_id} via SSE for real-time updates.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Arquivo inválido")

    content = await file.read()          # read before request ends
    job_id = create_job()
    background_tasks.add_task(_background_pipeline, job_id, content, file.filename)
    return {"job_id": job_id, "status": "processing"}


@router.get("/upload/progress/{job_id}")
async def upload_progress(job_id: str, request: Request) -> StreamingResponse:
    """
    SSE endpoint — streams JSON progress events until job completes or fails.
    Each event: data: {"status": ..., "step_label": ..., "progress_pct": ..., ...}
    """
    async def event_stream():
        while True:
            if await request.is_disconnected():
                break

            job = get_job(job_id)
            if job is None:
                yield f"data: {json.dumps({'error': 'job not found'})}\n\n"
                break

            yield f"data: {json.dumps(job.to_dict())}\n\n"

            if job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                break

            await asyncio.sleep(0.4)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",   # disable nginx buffering
        },
    )
