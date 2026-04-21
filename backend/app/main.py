import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import init_db
from app.routers import chat, insights, metrics, transactions, upload
from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


def _warmup_embedding_model() -> None:
    """
    Carrega o modelo fastembed/ONNX em memória durante o startup.

    Sem warm-up, a primeira query de chat leva ~2-5s a mais porque o ONNX
    Runtime precisa carregar o modelo do disco + JIT das ops. Após este
    pré-carregamento, todas as queries usam o modelo já em memória (<50ms).
    """
    try:
        from app.services.rag import _get_model
        logger.info("Pré-carregando modelo de embedding: %s…", settings.embedding_model)
        model = _get_model()
        # Inferência mínima para aquecer as ops ONNX e alocar buffers internos
        list(model.embed(["warmup"]))
        logger.info("Modelo de embedding pronto (warm-up concluído).")
    except Exception as exc:
        # Warm-up é best-effort — não impede o startup
        logger.warning("Warm-up do modelo falhou (será carregado na 1ª query): %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database…")
    init_db()

    # Warm-up em thread separada para não bloquear o event loop do FastAPI
    await asyncio.get_event_loop().run_in_executor(None, _warmup_embedding_model)

    logger.info("Backend ready 🚀")
    yield
    logger.info("Shutting down…")


app = FastAPI(
    title="Financial Intelligence API",
    version="1.0.0",
    description="AI-Powered Financial Analytics Platform",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router)
app.include_router(metrics.router)
app.include_router(transactions.router)
app.include_router(insights.router)
app.include_router(chat.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": "1.0.0"}


@app.post("/api/admin/reset-circuit")
def reset_circuit() -> dict:
    """Reseta manualmente o circuit breaker do LLM sem reiniciar o container."""
    from app.services._llm_state import reset_circuit as _reset
    _reset()
    return {"status": "ok", "message": "Circuit breaker resetado."}
