import logging
from typing import Optional
from fastapi import APIRouter, Query, HTTPException
from app.services.metrics_engine import get_metrics
from app.models.schemas import MetricsResponse

router = APIRouter(prefix="/api", tags=["metrics"])
logger = logging.getLogger(__name__)


@router.get("/metrics", response_model=MetricsResponse)
def metrics(
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    cliente: Optional[str] = Query(None),
) -> MetricsResponse:
    try:
        data = get_metrics(start_date=start_date, end_date=end_date, cliente=cliente)
        return MetricsResponse(**data)
    except Exception as exc:
        logger.exception("Erro ao calcular métricas")
        raise HTTPException(status_code=500, detail=str(exc))
