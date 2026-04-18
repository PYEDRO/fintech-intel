import logging
from fastapi import APIRouter, HTTPException
from app.services.rag import answer_question
from app.models.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/api", tags=["chat"])
logger = logging.getLogger(__name__)


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest) -> ChatResponse:
    try:
        result = await answer_question(body.question)
        return ChatResponse(**result)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.exception("Erro no chat RAG")
        raise HTTPException(status_code=500, detail=str(exc))
