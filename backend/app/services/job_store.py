"""
In-memory job store for tracking async ingestion pipeline progress.
Each upload spawns a background task; the frontend polls via SSE.
"""
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


PIPELINE_STEPS = [
    "Lendo e limpando arquivo",       # 1
    "Persistindo no banco de dados",   # 2
    "Classificando com IA (DeepSeek)", # 3
    "Indexando vetores (FAISS)",       # 4
    "Finalizando",                     # 5
]


@dataclass
class JobProgress:
    job_id: str
    status: JobStatus = JobStatus.PENDING
    step_label: str = "Aguardando início"
    step_index: int = 0
    total_steps: int = len(PIPELINE_STEPS)
    result: Optional[dict] = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "step_label": self.step_label,
            "step_index": self.step_index,
            "total_steps": self.total_steps,
            "progress_pct": round((self.step_index / self.total_steps) * 100),
            "result": self.result,
            "error": self.error,
        }


_store: dict[str, JobProgress] = {}
_MAX_JOBS = 200


def create_job() -> str:
    if len(_store) >= _MAX_JOBS:
        oldest = next(iter(_store))
        del _store[oldest]
    job_id = str(uuid.uuid4())
    _store[job_id] = JobProgress(job_id=job_id)
    return job_id


def update_job(job_id: str, **kwargs) -> None:
    if job_id in _store:
        for k, v in kwargs.items():
            setattr(_store[job_id], k, v)


def get_job(job_id: str) -> Optional[JobProgress]:
    return _store.get(job_id)
