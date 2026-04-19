import json
import logging
from pathlib import Path

import faiss
import numpy as np
import pandas as pd
from fastembed import TextEmbedding
from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

# fastembed usa ONNX — sem PyTorch, imagem Docker ~3.5GB menor
_model: TextEmbedding | None = None
_index: faiss.Index | None = None
_meta: list[dict] | None = None

RAG_SYSTEM_PROMPT = (
    "Você é um assistente de inteligência financeira. Responda perguntas sobre"
    " transações financeiras baseando-se EXCLUSIVAMENTE nos dados fornecidos no"
    " contexto.\n"
    "Regras:\n"
    "1. Cite os IDs das transações relevantes (ex: txn_00001)\n"
    "2. Forneça valores numéricos quando disponíveis\n"
    "3. Se a resposta não estiver nos dados, diga"
    ' "Não encontrei informações sobre isso nos dados disponíveis"\n'
    "4. Seja conciso mas completo\n"
    "5. Use formato monetário brasileiro (R$ X.XXX,XX)"
)


def _get_model() -> TextEmbedding:
    global _model
    if _model is None:
        logger.info("Carregando modelo fastembed: %s", settings.embedding_model)
        _model = TextEmbedding(model_name=settings.embedding_model)
    return _model


def _doc_text(row: dict) -> str:
    return (
        f"ID: {row.get('id')} | Cliente: {row.get('cliente')} | "
        f"Valor: R${row.get('valor'):.2f} | Data: {row.get('data')} | "
        f"Status: {row.get('status')} | Categoria: {row.get('categoria', 'N/A')} | "
        f"Descrição: {row.get('descricao')}"
    )


def _embed(texts: list[str]) -> np.ndarray:
    """Embed texts and return normalized float32 array."""
    model = _get_model()
    vecs = np.array(list(model.embed(texts)), dtype="float32")
    # L2-normalize for cosine similarity via inner product
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return vecs / norms


def build_faiss_index(df: pd.DataFrame) -> int:
    """Build FAISS IndexFlatIP from DataFrame and persist to disk."""
    global _index, _meta

    docs = [_doc_text(row) for row in df.to_dict("records")]
    embeddings = _embed(docs)

    index = faiss.IndexFlatIP(settings.embedding_dim)
    index.add(embeddings)

    Path(settings.faiss_index_path).parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, settings.faiss_index_path)

    meta = df[
        ["id", "descricao", "cliente", "valor", "status", "categoria"]
    ].to_dict("records")
    with open(settings.faiss_meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, default=str)

    _index = index
    _meta = meta
    return len(docs)


def _load_index() -> tuple[faiss.Index, list[dict]]:
    global _index, _meta
    if _index is None:
        if not Path(settings.faiss_index_path).exists():
            raise FileNotFoundError(
                "FAISS index não encontrado. Faça upload de dados primeiro."
            )
        _index = faiss.read_index(settings.faiss_index_path)
        with open(settings.faiss_meta_path, "r", encoding="utf-8") as f:
            _meta = json.load(f)
    return _index, _meta


def retrieve(question: str, k: int | None = None) -> list[dict]:
    """Embed question → FAISS top-K → return metadata with score."""
    k = k or settings.rag_top_k
    q_emb = _embed([question])

    index, meta = _load_index()
    scores, indices = index.search(q_emb, min(k, index.ntotal))

    results = []
    for score, idx in zip(scores[0], indices[0]):
        if idx < 0:
            continue
        entry = dict(meta[idx])
        entry["_score"] = float(score)
        results.append(entry)
    return results


async def answer_question(question: str) -> dict:
    """Full RAG pipeline: retrieve → build context → LLM answer."""
    sources = retrieve(question)

    context_lines = [_doc_text(s) for s in sources]
    context = "\n".join(context_lines)

    user_msg = f"Contexto das transações:\n{context}\n\nPergunta: {question}"

    answer_text = "Não encontrei informações sobre isso nos dados disponíveis"

    if settings.deepseek_api_key:
        client = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        )
        try:
            resp = await client.chat.completions.create(
                model=settings.deepseek_model,
                messages=[
                    {"role": "system", "content": RAG_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.2,
                max_tokens=1024,
            )
            answer_text = resp.choices[0].message.content.strip()
        except Exception as exc:
            logger.exception("RAG LLM call falhou: %s", exc)

    return {
        "answer": answer_text,
        "sources": [
            {
                "id": s["id"],
                "descricao": s["descricao"],
                "relevance": round(s["_score"], 4),
            }
            for s in sources
        ],
    }
