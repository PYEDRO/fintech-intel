"""
In-memory job store para rastreamento de uploads assíncronos.

Thread-safe via asyncio.Lock para uso em FastAPI single-worker.
Para produção multi-worker (GCP Cloud Run com múltiplas instâncias),
substituir por Redis ou Firestore (ver DEPLOY.md).
"""
import asyncio
import uuid
import logging
from datetime import datetime, timezone
from typing import Literal

logger = logging.getLogger(__name__)

JobStatus = Literal["queued", "processing", "done", "error"]


class JobStore:
    """Store singleton para jobs de upload."""

    def __init__(self) -> None:
        self._jobs: dict[str, dict] = {}
        self._lock = asyncio.Lock()

    async def create(self) -> str:
        """Cria um novo job e retorna seu ID."""
        job_id = uuid.uuid4().hex[:10]
        async with self._lock:
            self._jobs[job_id] = {
                "job_id": job_id,
                "status": "queued",
                "progress": 0,
                "step": "Na fila — aguardando processamento...",
                "result": None,
                "error": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        logger.info("Job criado: %s", job_id)
        return job_id

    async def update(self, job_id: str, **kwargs) -> None:
        """Atualiza campos do job (status, progress, step, result, error)."""
        async with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(kwargs)
                logger.debug(
                    "Job %s atualizado: %s",
                    job_id,
                    {k: v for k, v in kwargs.items() if k != "result"},
                )

    def get(self, job_id: str) -> dict | None:
        """Retorna o estado atual do job ou None se não existir."""
        return self._jobs.get(job_id)

    async def cleanup_old(self, max_age_seconds: int = 7200) -> None:
        """Remove jobs com mais de max_age_seconds (padrão: 2h)."""
        now = datetime.now(timezone.utc)
        async with self._lock:
            stale = [
                jid
                for jid, job in self._jobs.items()
                if (now - datetime.fromisoformat(job["created_at"])).total_seconds()
                > max_age_seconds
            ]
            for jid in stale:
                del self._jobs[jid]
            if stale:
                logger.info("Cleanup: %d jobs removidos.", len(stale))


# Singleton compartilhado por toda a aplicação
job_store = JobStore()
