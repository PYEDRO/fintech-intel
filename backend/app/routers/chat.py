"""
Router de chat com dois endpoints:

POST /api/chat          → resposta JSON completa via LangGraph agent
POST /api/chat/stream   → Server-Sent Events (streaming token-by-token)
"""
import json
import logging
from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from app.services.agent_graph import run_chat
from app.services.rag import stream_answer_question
from app.models.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/api", tags=["chat"])
logger = logging.getLogger(__name__)


# ── POST /api/chat — LangGraph, resposta JSON completa ────────────────────────

@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest) -> ChatResponse:
    """
    Executa o grafo LangGraph: supervisor → [sql_node | semantic_node].
    Retorna resposta JSON completa (sem streaming).
    """
    try:
        result = await run_chat(body.question)
        return ChatResponse(**result)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.exception("Erro no chat LangGraph")
        raise HTTPException(status_code=500, detail=str(exc))


# ── POST /api/chat/stream — SSE streaming token-by-token ──────────────────────

@router.post("/chat/stream")
async def chat_stream(body: ChatRequest) -> EventSourceResponse:
    """
    Retorna um stream SSE com eventos:
      data: {"type": "sources", "data": [...]}
      data: {"type": "token",   "data": "chunk de texto"}
      data: {"type": "done",    "data": ""}

    O frontend consome via fetch + ReadableStream (compatível com POST).
    """
    async def generator():
        try:
            async for event in stream_answer_question(body.question):
                yield json.dumps(event, ensure_ascii=False)
        except FileNotFoundError as exc:
            yield json.dumps({"type": "error", "data": f"Dados não encontrados: {exc}"})
            yield json.dumps({"type": "done", "data": ""})
        except Exception as exc:
            logger.exception("Erro no stream SSE")
            yield json.dumps({"type": "error", "data": f"Erro interno: {exc}"})
            yield json.dumps({"type": "done", "data": ""})

    return EventSourceResponse(generator())
