"""
LangGraph Supervisor Agent para o endpoint de chat.

Grafo de estados:
  START
    └─► supervisor_node   (classifica a intenção: sql | semantic)
          ├─► sql_node        (intenção agregada → query SQLite completo)
          └─► semantic_node   (busca específica → FAISS + LLM)
                └─► END

Por que LangGraph aqui?
  - O nó supervisor separa explicitamente "roteamento" de "execução".
  - Cada nó tem estado isolado → mais fácil adicionar novos nós no futuro
    (ex: verificação de crédito, alert node, etc).
  - O grafo pode ser inspecionado, visualizado e testado de forma independente.
  - Streaming via astream_events() quando o LLM suportar.
"""
from __future__ import annotations

import logging
from typing import TypedDict, Literal

from langgraph.graph import StateGraph, END

logger = logging.getLogger(__name__)


# ── Estado do grafo ────────────────────────────────────────────────────────────

class ChatState(TypedDict):
    question: str
    """Pergunta original do usuário."""

    intent: str | None
    """
    Intenção detectada pelo supervisor:
      "sql:<tipo>"  → ex: "sql:overdue", "sql:revenue"
      "semantic"    → busca semântica via FAISS
    """

    answer: str | None
    """Resposta gerada (preenchida por sql_node ou semantic_node)."""

    sources: list[dict]
    """Fontes utilizadas (transações do DB ou documentos FAISS)."""


# ── Nó 1: Supervisor ──────────────────────────────────────────────────────────

def supervisor_node(state: ChatState) -> dict:
    """
    Classifica a intenção da pergunta usando detecção rule-based (O(1), sem LLM).
    Perguntas de agregação → ramo SQL; buscas específicas → ramo semântico.
    """
    from app.services.rag import _detect_aggregate_intent

    question = state["question"]
    intent = _detect_aggregate_intent(question)
    routed = f"sql:{intent}" if intent else "semantic"

    logger.info("[Supervisor] '%s...' → %s", question[:50], routed)
    return {"intent": routed}


# ── Nó 2: SQL Tool ────────────────────────────────────────────────────────────

async def sql_node(state: ChatState) -> dict:
    """
    Executa query SQL no banco completo para perguntas de agregação.
    Dados vêm diretamente do SQLite → sem alucinação numérica.
    """
    from app.services.rag import _answer_aggregate

    # "sql:overdue" → intent_type="overdue"
    intent_type = state["intent"].split(":", 1)[1]
    logger.info("[SQL Node] intent_type=%s", intent_type)

    answer, sources = _answer_aggregate(intent_type, state["question"])
    return {"answer": answer, "sources": sources}


# ── Nó 3: Semantic RAG ────────────────────────────────────────────────────────

async def semantic_node(state: ChatState) -> dict:
    """
    Recupera documentos via FAISS e gera resposta com LLM (ou rule-based fallback).
    O prompt declara explicitamente que o contexto é uma amostra parcial.
    """
    from app.services.rag import (
        retrieve,
        _doc_text,
        RAG_SYSTEM_PROMPT,
        _rule_based_specific,
    )
    from app.config import settings
    from app.db import get_db
    from openai import AsyncOpenAI, APIStatusError
    from app.services._llm_state import api_available, mark_api_down

    question = state["question"]
    logger.info("[Semantic Node] FAISS retrieval: '%s...'", question[:50])

    sources = retrieve(question)
    if not sources:
        return {
            "answer": "Não encontrei transações relevantes para sua pergunta.",
            "sources": [],
        }

    try:
        with get_db() as conn:
            total_docs = conn.execute("SELECT COUNT(*) FROM transacoes").fetchone()[0]
    except Exception:
        total_docs = "?"

    context = "\n".join(_doc_text(s) for s in sources)
    user_msg = (
        f"Amostra semântica ({len(sources)} de {total_docs} transações totais):\n"
        f"{context}\n\nPergunta: {question}"
    )

    formatted_sources = [
        {"id": s["id"], "descricao": s["descricao"], "relevance": round(s["_score"], 4)}
        for s in sources
    ]

    if settings.llm_api_key and api_available():
        try:
            client = AsyncOpenAI(
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
                timeout=8.0,
            )
            prompt = RAG_SYSTEM_PROMPT.format(total_docs=total_docs)
            resp = await client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.2,
                max_tokens=1024,
            )
            answer = resp.choices[0].message.content.strip()
            logger.info("[Semantic Node] LLM (%d chars).", len(answer))
        except APIStatusError as exc:
            if exc.status_code in (401, 402):
                mark_api_down(f"HTTP {exc.status_code} — {exc.message}")
            else:
                logger.warning("[Semantic Node] LLM falhou: %s", exc)
            answer = _rule_based_specific(question, sources)
        except Exception as exc:
            logger.warning("[Semantic Node] LLM falhou → rule-based: %s", exc)
            answer = _rule_based_specific(question, sources)
    else:
        logger.info("[Semantic Node] LLM indisponível → rule-based.")
        answer = _rule_based_specific(question, sources)

    return {"answer": answer, "sources": formatted_sources}


# ── Roteador condicional ───────────────────────────────────────────────────────

def _route(state: ChatState) -> Literal["sql_node", "semantic_node"]:
    """Decide qual nó executar com base na intenção detectada pelo supervisor."""
    if (state.get("intent") or "").startswith("sql:"):
        return "sql_node"
    return "semantic_node"


# ── Compilação do grafo ────────────────────────────────────────────────────────

def build_chat_graph():
    """Constrói e compila o grafo de estados do agente de chat."""
    graph: StateGraph = StateGraph(ChatState)

    graph.add_node("supervisor", supervisor_node)
    graph.add_node("sql_node", sql_node)
    graph.add_node("semantic_node", semantic_node)

    graph.set_entry_point("supervisor")
    graph.add_conditional_edges(
        "supervisor",
        _route,
        {
            "sql_node": "sql_node",
            "semantic_node": "semantic_node",
        },
    )
    graph.add_edge("sql_node", END)
    graph.add_edge("semantic_node", END)

    compiled = graph.compile()
    logger.info("Chat graph compilado: supervisor → [sql_node | semantic_node] → END")
    return compiled


# Singleton compilado uma vez na inicialização do módulo
chat_graph = build_chat_graph()


# ── Helper de invocação ───────────────────────────────────────────────────────

async def run_chat(question: str) -> dict:
    """
    Executa o grafo e retorna {"answer": str, "sources": list[dict]}.
    Chamado pelo router de chat para o endpoint POST /api/chat.
    """
    initial: ChatState = {
        "question": question,
        "intent": None,
        "answer": None,
        "sources": [],
    }
    final: ChatState = await chat_graph.ainvoke(initial)
    return {
        "answer": final.get("answer") or "Não foi possível gerar uma resposta.",
        "sources": final.get("sources") or [],
    }
