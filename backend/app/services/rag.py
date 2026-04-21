import json
import logging
from pathlib import Path

import faiss
import numpy as np
import pandas as pd
from fastembed import TextEmbedding
from openai import AsyncOpenAI, APIStatusError

from app.config import settings
from app.db import get_db
from app.services._llm_state import api_available, mark_api_down

logger = logging.getLogger(__name__)

# fastembed usa ONNX — sem PyTorch, imagem Docker ~3.5GB menor
_model: TextEmbedding | None = None
_index: faiss.Index | None = None
_meta: list[dict] | None = None

# ── Prompt do LLM ─────────────────────────────────────────────────────────────
# O contexto enviado ao LLM é sempre uma AMOSTRA semântica (top-K), nunca o
# dataset completo. O prompt deixa isso EXPLÍCITO para evitar alucinações em
# perguntas de agregação.
RAG_SYSTEM_PROMPT = """Você é um assistente de inteligência financeira.

IMPORTANTE — CONTEXTO LIMITADO:
Os dados abaixo são uma AMOSTRA semântica das transações mais relevantes
para a pergunta (tipicamente 10-15 de {total_docs} transações totais no
banco). NÃO são o dataset completo.

Regras obrigatórias:
1. NUNCA calcule ou afirme totais (receita total, contagem total, valor
   total) baseando-se nesta amostra — esses valores estarão errados.
2. Para perguntas de agregação ("total", "quanto", "quantas", "maior
   cliente", "taxa de inadimplência"), oriente o usuário a usar o
   Dashboard ou informe que esses dados são do sistema de métricas.
3. Para BUSCAS ESPECÍFICAS (detalhar uma transação, listar exemplos,
   descrever padrões), responda com base nos dados fornecidos.
4. Cite os IDs das transações relevantes (ex: txn_00001).
5. Use formato monetário brasileiro (R$ X.XXX,XX).
6. Se a pergunta for de agregação mas os dados foram pré-calculados do
   banco completo (virão marcados com [DADOS COMPLETOS]), confie neles
   e os apresente sem ressalvas."""

# ── Padrões de intenção agregada ──────────────────────────────────────────────
# Perguntas que exigem dados do banco completo, não de amostra FAISS.
_AGGREGATE_PATTERNS: list[tuple[list[str], str]] = [
    # ── RATE antes de OVERDUE para capturar "taxa de inadimplência" primeiro ──
    (["taxa de inadimplencia", "taxa de inadimplência", "percentual",
      "porcentagem de inadimpl", "% de atraso"],                            "rate"),
    # ── BY_CLIENT antes de OVERDUE para capturar "cliente com inadimplência" ─
    (["maior cliente", "top cliente", "maior faturador", "cliente com mais",
      "qual cliente tem", "ranking de client", "por cliente",
      "qual cliente", "inadimpl"],                               "by_client"),
    # ── OVERDUE: apenas sinais claros de status atrasado ─────────────────────
    (["atrasad", "vencid", "overdue", "em atraso"],                         "overdue"),
    # ── REVENUE ───────────────────────────────────────────────────────────────
    (["receita total", "faturamento total", "total pago", "total faturad",
      "quanto foi pago", "total de receita", "receita geral"],              "revenue"),
    # ── PENDING ───────────────────────────────────────────────────────────────
    (["pendente", "aguardando pagamento", "a receber", "nao pago",
      "não pago", "carteira pendente"],                                     "pending"),
    # ── COUNT ─────────────────────────────────────────────────────────────────
    (["quantas transacoes", "total de transacoes", "numero de transacoes",
      "quantas transações", "total transações"],                            "count"),
    # ── EXTREMES: maior/menor em valor ────────────────────────────────────────
    (["maiores transacoes", "maiores transações", "maior transacao",
      "maior transação", "maior valor", "menores transacoes",
      "menores transações", "menor transacao", "menor transação",
      "menor valor", "mais alto", "mais baixo", "mais caras", "mais baratas"],
                                                                            "extremes"),
]


def _detect_aggregate_intent(question: str) -> str | None:
    """Retorna o tipo de intenção agregada ou None se for busca específica."""
    q = question.lower()
    for patterns, intent_type in _AGGREGATE_PATTERNS:
        if any(p in q for p in patterns):
            return intent_type
    return None


# ── Respostas diretas ao banco (sem FAISS) ────────────────────────────────────

def _answer_overdue() -> tuple[str, list[dict]]:
    """Consulta transações atrasadas diretamente no SQLite."""
    with get_db() as conn:
        summary = conn.execute(
            "SELECT COUNT(*) AS cnt, COALESCE(SUM(valor), 0) AS soma "
            "FROM transacoes WHERE status='atrasado'"
        ).fetchone()
        top = conn.execute(
            "SELECT id, cliente, valor, data, descricao "
            "FROM transacoes WHERE status='atrasado' "
            "ORDER BY valor DESC LIMIT 15"
        ).fetchall()

    cnt, soma = summary["cnt"], summary["soma"]
    if cnt == 0:
        return "Não há transações com status 'atrasado' no banco de dados.", []

    linhas = "\n".join(
        f"• {r['id']} | {r['cliente']} | R${r['valor']:,.2f} | "
        f"{r['data']} | {r['descricao'][:60]}"
        for r in top
    )
    answer = (
        f"[DADOS COMPLETOS DO BANCO]\n"
        f"Total de transações atrasadas: {cnt}\n"
        f"Valor total em atraso: R${soma:,.2f}\n\n"
        f"As {len(top)} de maior valor:\n{linhas}"
    )
    sources = [
        {"id": r["id"], "descricao": r["descricao"], "relevance": 1.0} for r in top
    ]
    return answer, sources


def _answer_revenue() -> tuple[str, list[dict]]:
    """Receita total diretamente do banco."""
    with get_db() as conn:
        r = conn.execute(
            """SELECT
                COALESCE(SUM(CASE WHEN status='pago' THEN valor ELSE 0 END), 0)
                    AS receita,
                COALESCE(SUM(valor), 0) AS total_geral,
                COUNT(*) AS total_txn,
                SUM(CASE WHEN status='pago' THEN 1 ELSE 0 END) AS pagas,
                SUM(CASE WHEN status='pendente' THEN 1 ELSE 0 END) AS pendentes,
                SUM(CASE WHEN status='atrasado' THEN 1 ELSE 0 END) AS atrasadas
            FROM transacoes"""
        ).fetchone()
        top = conn.execute(
            "SELECT id, cliente, valor, data, descricao FROM transacoes "
            "WHERE status='pago' ORDER BY valor DESC LIMIT 10"
        ).fetchall()

    linhas = "\n".join(
        f"• {row['id']} | {row['cliente']} | R${row['valor']:,.2f} | {row['data']}"
        for row in top
    )
    answer = (
        f"[DADOS COMPLETOS DO BANCO]\n"
        f"Receita confirmada (status=pago): R${r['receita']:,.2f}\n"
        f"Volume total (todos os status): R${r['total_geral']:,.2f}\n"
        f"Total de transações: {r['total_txn']} "
        f"({r['pagas']} pagas | {r['pendentes']} pendentes | "
        f"{r['atrasadas']} atrasadas)\n\n"
        f"Maiores receitas individuais:\n{linhas}"
    )
    sources = [
        {"id": r["id"], "descricao": r["descricao"], "relevance": 1.0} for r in top
    ]
    return answer, sources


def _answer_pending() -> tuple[str, list[dict]]:
    """Transações pendentes diretamente do banco."""
    with get_db() as conn:
        summary = conn.execute(
            "SELECT COUNT(*) AS cnt, COALESCE(SUM(valor), 0) AS soma "
            "FROM transacoes WHERE status='pendente'"
        ).fetchone()
        top = conn.execute(
            "SELECT id, cliente, valor, data, descricao "
            "FROM transacoes WHERE status='pendente' "
            "ORDER BY valor DESC LIMIT 15"
        ).fetchall()

    cnt, soma = summary["cnt"], summary["soma"]
    if cnt == 0:
        return "Não há transações pendentes no banco de dados.", []

    linhas = "\n".join(
        f"• {r['id']} | {r['cliente']} | R${r['valor']:,.2f} | {r['data']}"
        for r in top
    )
    answer = (
        f"[DADOS COMPLETOS DO BANCO]\n"
        f"Total de transações pendentes: {cnt}\n"
        f"Valor total pendente (a receber): R${soma:,.2f}\n\n"
        f"As {len(top)} de maior valor:\n{linhas}"
    )
    sources = [
        {"id": r["id"], "descricao": r["descricao"], "relevance": 1.0} for r in top
    ]
    return answer, sources


def _answer_by_client() -> tuple[str, list[dict]]:
    """Ranking de clientes diretamente do banco."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT
                cliente,
                COUNT(*) AS total,
                COALESCE(SUM(CASE WHEN status='pago' THEN valor ELSE 0 END), 0)
                    AS receita,
                SUM(CASE WHEN status='atrasado' THEN 1 ELSE 0 END) AS atrasadas,
                SUM(CASE WHEN status='pendente' THEN 1 ELSE 0 END) AS pendentes,
                ROUND(CAST(SUM(CASE WHEN status='atrasado' THEN 1 ELSE 0 END)
                    AS FLOAT) / COUNT(*) * 100, 1) AS taxa_inadimpl
            FROM transacoes
            GROUP BY cliente
            ORDER BY receita DESC"""
        ).fetchall()

    if not rows:
        return "Não há dados de clientes no banco.", []

    linhas = "\n".join(
        f"• {r['cliente']}: {r['total']} txn | "
        f"Receita: R${r['receita']:,.2f} "
        f"| Atrasadas: {r['atrasadas']} ({r['taxa_inadimpl']}%) "
        f"| Pendentes: {r['pendentes']}"
        for r in rows
    )
    answer = (
        f"[DADOS COMPLETOS DO BANCO] "
        f"Ranking de clientes ({len(rows)} total):\n{linhas}"
    )
    return answer, []


def _answer_extremes(question: str) -> tuple[str, list[dict]]:
    """Maiores/menores transações diretamente do banco."""
    q = question.lower()
    asc = any(kw in q for kw in ["menor", "mais baix", "mais barato"])
    order = "ASC" if asc else "DESC"
    label = "menores" if asc else "maiores"

    with get_db() as conn:
        top = conn.execute(
            f"SELECT id, cliente, valor, data, status, descricao "
            f"FROM transacoes ORDER BY valor {order} LIMIT 10"
        ).fetchall()

    linhas = "\n".join(
        f"• {r['id']} | {r['cliente']} | R${r['valor']:,.2f} "
        f"| {r['status']} | {r['data']}"
        for r in top
    )
    answer = (
        f"[DADOS COMPLETOS DO BANCO] As 10 transações de {label} valor:\n{linhas}"
    )
    sources = [
        {"id": r["id"], "descricao": r["descricao"], "relevance": 1.0} for r in top
    ]
    return answer, sources


def _answer_rate() -> tuple[str, list[dict]]:
    """Taxa de inadimplência e métricas gerais."""
    with get_db() as conn:
        r = conn.execute(
            """SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status='atrasado' THEN 1 ELSE 0 END) AS atrasadas,
                SUM(CASE WHEN status='pendente' THEN 1 ELSE 0 END) AS pendentes,
                SUM(CASE WHEN status='pago' THEN 1 ELSE 0 END) AS pagas,
                ROUND(CAST(SUM(CASE WHEN status='atrasado' THEN 1 ELSE 0 END)
                    AS FLOAT) / COUNT(*) * 100, 2) AS taxa_inadimpl,
                COALESCE(SUM(CASE WHEN status='atrasado' THEN valor ELSE 0 END), 0)
                    AS valor_inadimpl,
                COALESCE(SUM(valor), 0) AS valor_total
            FROM transacoes"""
        ).fetchone()

    pct_vol = (
        round(r["valor_inadimpl"] / r["valor_total"] * 100, 2)
        if r["valor_total"] else 0
    )
    answer = (
        f"[DADOS COMPLETOS DO BANCO]\n"
        f"Taxa de inadimplência: {r['taxa_inadimpl']}% "
        f"({r['atrasadas']} de {r['total']} transações)\n"
        f"Valor em atraso: R${r['valor_inadimpl']:,.2f} "
        f"de R${r['valor_total']:,.2f} ({pct_vol}% do volume)\n"
        f"Distribuição: {r['pagas']} pagas | {r['pendentes']} pendentes "
        f"| {r['atrasadas']} atrasadas"
    )
    return answer, []


def _answer_count() -> tuple[str, list[dict]]:
    """Contagem geral de transações."""
    with get_db() as conn:
        r = conn.execute(
            """SELECT COUNT(*) AS total,
               SUM(CASE WHEN status='pago' THEN 1 ELSE 0 END) AS pagas,
               SUM(CASE WHEN status='pendente' THEN 1 ELSE 0 END) AS pendentes,
               SUM(CASE WHEN status='atrasado' THEN 1 ELSE 0 END) AS atrasadas
            FROM transacoes"""
        ).fetchone()

    answer = (
        f"[DADOS COMPLETOS DO BANCO]\n"
        f"Total de transações: {r['total']}\n"
        f"  • Pagas: {r['pagas']}\n"
        f"  • Pendentes: {r['pendentes']}\n"
        f"  • Atrasadas: {r['atrasadas']}"
    )
    return answer, []


# ── Dispatch de intenção agregada ─────────────────────────────────────────────

def _answer_aggregate(intent: str, question: str) -> tuple[str, list[dict]]:
    """Roteador: direciona para a query SQL correta segundo a intenção."""
    dispatch = {
        "overdue":    _answer_overdue,
        "revenue":    _answer_revenue,
        "pending":    _answer_pending,
        "by_client":  _answer_by_client,
        "rate":       _answer_rate,
        "count":      _answer_count,
    }
    if intent == "extremes":
        return _answer_extremes(question)
    if intent in dispatch:
        return dispatch[intent]()
    # Fallback seguro
    return _answer_revenue()


# ── FAISS helpers ──────────────────────────────────────────────────────────────

def _get_model() -> TextEmbedding:
    global _model
    if _model is None:
        logger.info("Carregando modelo fastembed: %s", settings.embedding_model)
        _model = TextEmbedding(model_name=settings.embedding_model)
    return _model


def _doc_text(row: dict) -> str:
    valor = row.get("valor") or 0.0
    return (
        f"ID: {row.get('id')} | Cliente: {row.get('cliente')} | "
        f"Valor: R${float(valor):.2f} | Data: {row.get('data', 'N/A')} | "
        f"Status: {row.get('status')} | Categoria: {row.get('categoria', 'N/A')} | "
        f"Descrição: {row.get('descricao')}"
    )


def _embed(texts: list[str]) -> np.ndarray:
    model = _get_model()
    vecs = np.array(list(model.embed(texts)), dtype="float32")
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

    cols = ["id", "descricao", "cliente", "valor", "data", "status", "categoria"]
    meta = df[cols].to_dict("records")
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


# ── Fallback rule-based para busca específica (sem LLM) ───────────────────────

def _rule_based_specific(question: str, sources: list[dict]) -> str:
    """Resposta baseada em regras para buscas específicas.
    Usa APENAS os sources recebidos, nunca extrapola para o dataset completo."""
    if not sources:
        return "Não encontrei transações relevantes para sua pergunta."

    n = len(sources)
    linhas = "\n".join(
        f"• {s['id']} | {s.get('cliente','?')} "
        f"| R${float(s.get('valor') or 0):,.2f}"
        f" | {s.get('status','?')} | {s.get('data','N/A')}"
        f" | {s.get('descricao','')[:70]}"
        for s in sources[:10]
    )
    return (
        f"Transações mais semanticamente relevantes para sua pergunta "
        f"({n} documentos recuperados por similaridade):\n\n{linhas}"
    )


# ── Pipeline principal ─────────────────────────────────────────────────────────

async def answer_question(question: str) -> dict:
    """Bifurca por intenção:
    - Aggregate intent → query SQLite completo (sem alucinação)
    - Specific lookup  → FAISS + LLM (com contexto declarando que é amostra)
    """
    intent = _detect_aggregate_intent(question)

    # ── Ramo 1: Pergunta de agregação → banco completo ────────────────────────
    if intent:
        logger.info(
            "Intenção agregada detectada: %s — consultando banco completo.", intent
        )
        answer_text, db_sources = _answer_aggregate(intent, question)

        # Com LLM: enriquece a apresentação mas com dados já corretos do banco
        if settings.llm_api_key and api_available() and db_sources:
            try:
                client = AsyncOpenAI(
                    api_key=settings.llm_api_key,
                    base_url=settings.llm_base_url,
                    timeout=8.0,
                )
                prompt = RAG_SYSTEM_PROMPT.format(total_docs=len(db_sources))
                resp = await client.chat.completions.create(
                    model=settings.llm_model,
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": (
                            f"Contexto [DADOS COMPLETOS DO BANCO]:\n{answer_text}\n\n"
                            f"Pergunta: {question}\n\n"
                            "Apresente os dados de forma clara e estruturada. "
                            "NÃO altere os valores numéricos fornecidos."
                        )},
                    ],
                    temperature=0.1,
                    max_tokens=800,
                )
                llm_text = resp.choices[0].message.content.strip()
                logger.info("LLM formatou resposta agregada.")
                return {"answer": llm_text, "sources": db_sources}
            except APIStatusError as exc:
                if exc.status_code in (400, 401, 402, 403, 404):
                    mark_api_down(f"HTTP {exc.status_code} — {exc.message}")
                else:
                    logger.warning("LLM falhou no ramo agregado: %s", exc)
            except Exception as exc:
                logger.warning(
                    "LLM falhou no ramo agregado, retornando dado bruto: %s", exc
                )

        return {"answer": answer_text, "sources": db_sources}

    # ── Ramo 2: Busca específica → FAISS + LLM ───────────────────────────────
    logger.info("Busca específica — usando FAISS + LLM.")
    sources = retrieve(question)

    if not sources:
        return {
            "answer": "Não encontrei transações relevantes para sua pergunta.",
            "sources": [],
        }

    # Conta total de docs no banco para informar o LLM
    try:
        with get_db() as conn:
            total_docs = conn.execute("SELECT COUNT(*) FROM transacoes").fetchone()[0]
    except Exception:
        total_docs = "?"

    context = "\n".join(_doc_text(s) for s in sources)
    user_msg = (
        f"Amostra semântica ({len(sources)} de {total_docs} transações totais):\n"
        f"{context}\n\n"
        f"Pergunta: {question}"
    )

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
            answer_text = resp.choices[0].message.content.strip()
            logger.info("RAG LLM respondeu (%d chars).", len(answer_text))
        except APIStatusError as exc:
            if exc.status_code in (400, 401, 402, 403, 404):
                mark_api_down(f"HTTP {exc.status_code} — {exc.message}")
            else:
                logger.warning("RAG LLM falhou: %s", exc)
            answer_text = _rule_based_specific(question, sources)
        except Exception as exc:
            logger.warning("RAG LLM falhou — usando rule-based. Erro: %s", exc)
            answer_text = _rule_based_specific(question, sources)
    else:
        logger.info("LLM indisponível — usando rule-based.")
        answer_text = _rule_based_specific(question, sources)

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


# ── Streaming (SSE) ───────────────────────────────────────────────────────────

def _text_chunks(text: str, size: int = 40) -> list[str]:
    """Divide texto em chunks para simular streaming em respostas determinísticas."""
    return [text[i : i + size] for i in range(0, len(text), size)]


async def stream_answer_question(question: str):
    """
    Async generator que produz eventos SSE para o endpoint /api/chat/stream.

    Protocolo de eventos:
      {"type": "sources", "data": [...]}   ← enviado primeiro (FAISS ou DB)
      {"type": "token",   "data": "..."}   ← tokens LLM (ou chunks simulados)
      {"type": "done",    "data": ""}      ← sinaliza fim do stream
    """
    intent = _detect_aggregate_intent(question)

    # ── Ramo SQL: dados do banco completo ─────────────────────────────────────
    if intent:
        logger.info("[Stream] intenção agregada: %s", intent)
        answer, db_sources = _answer_aggregate(intent, question)

        yield {"type": "sources", "data": db_sources}

        # Simula streaming do texto já pronto em chunks
        for chunk in _text_chunks(answer):
            yield {"type": "token", "data": chunk}

        yield {"type": "done", "data": ""}
        return

    # ── Ramo Semântico: FAISS + LLM com streaming real ────────────────────────
    logger.info("[Stream] busca semântica para: %r", question[:60])
    sources = retrieve(question)

    formatted_sources = [
        {"id": s["id"], "descricao": s["descricao"], "relevance": round(s["_score"], 4)}
        for s in sources
    ]
    yield {"type": "sources", "data": formatted_sources}

    if not sources:
        yield {"type": "token", "data": "Não encontrei transações relevantes para sua pergunta."}
        yield {"type": "done", "data": ""}
        return

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

    if settings.llm_api_key and api_available():
        try:
            client = AsyncOpenAI(
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
                timeout=8.0,
            )
            prompt = RAG_SYSTEM_PROMPT.format(total_docs=total_docs)
            # stream=True → tokens gerados incrementalmente pela API
            stream = await client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.2,
                max_tokens=1024,
                stream=True,
            )
            async for chunk in stream:
                token = chunk.choices[0].delta.content
                if token:
                    yield {"type": "token", "data": token}
            yield {"type": "done", "data": ""}
            return
        except APIStatusError as exc:
            if exc.status_code in (400, 401, 402, 403, 404):
                mark_api_down(f"HTTP {exc.status_code} — {exc.message}")
            else:
                logger.warning("[Stream] LLM falhou: %s", exc)
        except Exception as exc:
            logger.warning("[Stream] LLM falhou — usando rule-based. Erro: %s", exc)

    # Fallback rule-based (sem LLM ou após circuit breaker)
    logger.info("[Stream] usando rule-based.")
    fallback = _rule_based_specific(question, sources)
    for chunk in _text_chunks(fallback):
        yield {"type": "token", "data": chunk}

    yield {"type": "done", "data": ""}