import logging
from fastapi import APIRouter, HTTPException
from app.services.insights_gen import generate_insights
from app.models.schemas import InsightsResponse

router = APIRouter(prefix="/api", tags=["insights"])
logger = logging.getLogger(__name__)


@router.get("/insights", response_model=InsightsResponse)
async def insights() -> InsightsResponse:
    try:
        result = await generate_insights()
        return InsightsResponse(**result)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.exception("Erro ao gerar insights")
        raise HTTPException(status_code=500, detail=str(exc))
