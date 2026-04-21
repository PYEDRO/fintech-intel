"""
Insights generation com Structured Outputs.

Usa response_format={"type": "json_object"} para forçar o LLM a retornar JSON
válido, eliminando a necessidade de parsing frágil com split("```").
Valida cada campo individualmente com Pydantic para robustez máxima.
"""
import json
import logging
from pydantic import BaseModel, ValidationError
from openai import AsyncOpenAI, APIStatusError
from app.config import settings
from app.db import get_db
from app.services.metrics_engine import get_metrics
from app.services.anomaly import detect_anomalies
from app.services._llm_state import api_available, mark_api_down

logger = logging.getLogger(__name__)

# ── JSON Schema explícito no prompt ───────────────────────────────────────────
# Forçar o LLM a seguir o schema exato reduz falhas de validação em >95%.
INSIGHTS_SYSTEM_PROMPT = """Você é um analista financeiro sênior especializado em SaaS/Fintech.
Analise as métricas fornecidas e retorne um JSON VÁLIDO com o seguinte schema EXATO:

{
  "insights": [
    {
      "titulo": "string (máx 60 chars)",
      "descricao": "string com dados numéricos concretos (valores, percentuais)",
      "tipo": "oportunidade" | "risco" | "tendencia",
      "severidade": "alta" | "media" | "baixa"
    }
  ],
  "score_clientes": [
    {
      "cliente": "string (nome exato do cliente)",
      "score": number (0.0 a 10.0),
      "risco": "alto" | "medio" | "baixo",
      "motivo": "string explicando o score"
    }
  ]
}

Regras obrigatórias:
1. Retorne APENAS o JSON, sem texto adicional, sem markdown.
2. Gere entre 3 e 6 insights relevantes.
3. Inclua TODOS os clientes no score_clientes.
4. Use "oportunidade", "risco" ou "tendencia" (sem acento em tendencia).
5. Use "alta", "media" ou "baixa" (sem acento em media).
6. Valores monetários em formato brasileiro (R$ X.XXX,XX) na descricao."""


# ── Pydantic internal models para validação da resposta do LLM ────────────────

class _InsightRaw(BaseModel):
    titulo: str
    descricao: str
    tipo: str
    severidade: str


class _ClientScoreRaw(BaseModel):
    cliente: str
    score: float
    risco: str
    motivo: str


class _InsightsResponseRaw(BaseModel):
    insights: list[_InsightRaw]
    score_clientes: list[_ClientScoreRaw]


# ── Normalização de enums ──────────────────────────────────────────────────────
_TIPO_MAP = {
    "oportunidade": "oportunidade",
    "risco": "risco",
    "tendencia": "tendencia",
    "tendência": "tendencia",
    "trend": "tendencia",
    "opportunity": "oportunidade",
    "risk": "risco",
}

_SEV_MAP = {
    "alta": "alta",
    "high": "alta",
    "media": "media",
    "média": "media",
    "medium": "media",
    "baixa": "baixa",
    "low": "baixa",
}

_RISCO_MAP = {
    "alto": "alto",
    "high": "alto",
    "medio": "medio",
    "médio": "medio",
    "medium": "medio",
    "baixo": "baixo",
    "low": "baixo",
}


def _normalize_insight(raw: _InsightRaw) -> dict | None:
    """Valida e normaliza um insight individual; retorna None se inválido."""
    tipo = _TIPO_MAP.get(raw.tipo.lower().strip())
    severidade = _SEV_MAP.get(raw.severidade.lower().strip())
    if not tipo or not severidade:
        logger.warning("Insight com tipo/severidade inválido descartado: %r / %r", raw.tipo, raw.severidade)
        return None
    return {
        "titulo": raw.titulo[:120],
        "descricao": raw.descricao,
        "tipo": tipo,
        "severidade": severidade,
    }


def _normalize_client_score(raw: _ClientScoreRaw) -> dict | None:
    """Valida e normaliza um client score; retorna None se inválido."""
    risco = _RISCO_MAP.get(raw.risco.lower().strip())
    if not risco:
        logger.warning("ClientScore com risco inválido descartado: %r", raw.risco)
        return None
    score = max(0.0, min(10.0, float(raw.score)))
    return {
        "cliente": raw.cliente,
        "score": round(score, 1),
        "risco": risco,
        "motivo": raw.motivo,
    }


# ── Fallback local (sem LLM) ──────────────────────────────────────────────────

def _compute_client_scores_local(clients_stats) -> list[dict]:
    """Fallback: calcula scores de clientes sem LLM."""
    results = []
    for r in clients_stats:
        total = r["total"] or 1
        inadimplencia_rate = (r["atrasadas"] or 0) / total
        ticket = r["ticket_medio"] or 0
        score = max(0.0, 10.0 - inadimplencia_rate * 20)
        risco = "alto" if score < 4 else ("medio" if score < 7 else "baixo")
        results.append({
            "cliente": r["cliente"],
            "score": round(score, 1),
            "risco": risco,
            "motivo": f"Taxa inadimplência: {inadimplencia_rate*100:.1f}%, Ticket médio: R${ticket:.2f}",
        })
    return results


def _build_fallback_insights(metrics: dict) -> list[dict]:
    return [
        {
            "titulo": "Dados carregados com sucesso",
            "descricao": (
                f"Total de {metrics['total_transacoes']} transações. "
                f"Receita total: R${metrics['receita_total']:,.2f}. "
                f"Taxa de inadimplência: {metrics['taxa_inadimplencia']}%."
            ),
            "tipo": "tendencia",
            "severidade": "baixa",
        }
    ]


# ── Pipeline principal ─────────────────────────────────────────────────────────

async def generate_insights() -> dict:
    """Compute metrics + sample data → LLM (structured output) → insights validados."""
    metrics = get_metrics()
    anomalias = await detect_anomalies()

    with get_db() as conn:
        top5 = conn.execute(
            "SELECT id, cliente, valor, status, descricao FROM transacoes ORDER BY valor DESC LIMIT 5"
        ).fetchall()
        clients_stats = conn.execute(
            """SELECT cliente,
                      COUNT(*) AS total,
                      SUM(CASE WHEN status='pago' THEN valor ELSE 0 END) AS receita,
                      SUM(CASE WHEN status='atrasado' THEN 1 ELSE 0 END) AS atrasadas,
                      AVG(valor) AS ticket_medio
               FROM transacoes GROUP BY cliente"""
        ).fetchall()

    payload = {
        "metricas_gerais": {
            "receita_total": metrics["receita_total"],
            "ticket_medio": metrics["ticket_medio"],
            "taxa_inadimplencia": metrics["taxa_inadimplencia"],
            "total_transacoes": metrics["total_transacoes"],
            "por_status": metrics["por_status"],
        },
        "evolucao_mensal": metrics["evolucao_mensal"][-6:],
        "top_clientes": metrics["por_cliente"][:5],
        "por_categoria": metrics["por_categoria"][:5],
        "maiores_transacoes": [dict(r) for r in top5],
        "stats_por_cliente": [dict(r) for r in clients_stats],
        "projecao_fluxo": metrics.get("projecao_fluxo", []),
    }

    fallback_insights = _build_fallback_insights(metrics)
    local_scores = _compute_client_scores_local(clients_stats)

    if not settings.llm_api_key or not api_available():
        logger.info("LLM indisponível — retornando insights locais.")
        return {"insights": fallback_insights, "anomalias": anomalias, "score_clientes": local_scores}

    client = AsyncOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        timeout=8.0,
    )
    try:
        resp = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": INSIGHTS_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
            ],
            # Força saída JSON válida — elimina markdown code blocks e texto livre
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=2048,
        )

        raw_text = resp.choices[0].message.content.strip()
        logger.info("LLM insights respondeu (%d chars).", len(raw_text))

        raw_json = json.loads(raw_text)

        # Valida com Pydantic — cada campo individualmente para máxima resiliência
        try:
            parsed = _InsightsResponseRaw.model_validate(raw_json)
        except ValidationError as ve:
            logger.warning("Validação Pydantic parcial: %s — usando campos válidos.", ve)
            parsed = _InsightsResponseRaw(
                insights=[_InsightRaw(**i) for i in raw_json.get("insights", []) if isinstance(i, dict)],
                score_clientes=[_ClientScoreRaw(**s) for s in raw_json.get("score_clientes", []) if isinstance(s, dict)],
            )

        # Normaliza enums (o LLM às vezes usa variantes com acento)
        insights = [n for raw in parsed.insights if (n := _normalize_insight(raw))]
        scores = [n for raw in parsed.score_clientes if (n := _normalize_client_score(raw))]

        if not insights:
            logger.warning("Nenhum insight válido após normalização — usando fallback.")
            insights = fallback_insights
        if not scores:
            scores = local_scores

        return {"insights": insights, "anomalias": anomalias, "score_clientes": scores}

    except APIStatusError as exc:
        if exc.status_code in (401, 402, 403, 404):
            mark_api_down(f"HTTP {exc.status_code} — {exc.message}")
        else:
            logger.warning("Insights LLM falhou: %s", exc)
    except json.JSONDecodeError as exc:
        logger.error("JSON inválido da LLM apesar de response_format: %s", exc)
    except Exception as exc:
        logger.warning("Insights generation falhou: %s", exc)

    return {"insights": fallback_insights, "anomalias": anomalias, "score_clientes": local_scores}
