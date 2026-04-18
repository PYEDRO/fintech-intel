"""
LLM insights generator with structured output + Pydantic validation.
Falls back to local heuristics if LLM fails or key is absent.
"""
import json
import logging
from typing import List
from pydantic import BaseModel, field_validator
from openai import AsyncOpenAI
from app.config import settings
from app.db import get_db
from app.services.metrics_engine import get_metrics
from app.services.anomaly import detect_anomalies
from app.repositories.transaction_repository import TransactionRepository

logger = logging.getLogger(__name__)

INSIGHTS_SYSTEM_PROMPT = """Você é um analista financeiro sênior. Analise as métricas e gere de 3 a 5 insights acionáveis.

Para cada insight:
- titulo: título curto e direto
- descricao: descrição com dados concretos (valores, percentuais)
- tipo: exatamente "oportunidade", "risco" ou "tendencia"
- severidade: exatamente "alta", "media" ou "baixa"

Para cada cliente:
- cliente: nome do cliente
- score: número de 0 a 10 (saúde financeira)
- risco: exatamente "alto", "medio" ou "baixo"
- motivo: justificativa objetiva

Responda APENAS com JSON válido:
{"insights": [...], "score_clientes": [...]}"""


# ── Pydantic schemas para validação ──────────────────────────────────────────

class InsightItem(BaseModel):
    titulo: str
    descricao: str
    tipo: str
    severidade: str

    @field_validator("tipo")
    @classmethod
    def validate_tipo(cls, v: str) -> str:
        return v if v in {"oportunidade", "risco", "tendencia"} else "tendencia"

    @field_validator("severidade")
    @classmethod
    def validate_severidade(cls, v: str) -> str:
        return v if v in {"alta", "media", "baixa"} else "media"


class ClientScoreItem(BaseModel):
    cliente: str
    score: float
    risco: str
    motivo: str

    @field_validator("risco")
    @classmethod
    def validate_risco(cls, v: str) -> str:
        return v if v in {"alto", "medio", "baixo"} else "medio"

    @field_validator("score")
    @classmethod
    def clamp_score(cls, v: float) -> float:
        return round(max(0.0, min(10.0, v)), 1)


class LLMInsightsResponse(BaseModel):
    insights: List[InsightItem]
    score_clientes: List[ClientScoreItem]


# ── Local fallback: client scores without LLM ────────────────────────────────

def _local_client_scores(clients_stats: list[dict]) -> list[dict]:
    results = []
    for r in clients_stats:
        total = r["total"] or 1
        taxa = r["atrasadas"] / total
        score = round(max(0.0, 10.0 - taxa * 20), 1)
        risco = "alto" if score < 4 else ("medio" if score < 7 else "baixo")
        results.append({
            "cliente": r["cliente"],
            "score": score,
            "risco": risco,
            "motivo": f"Taxa inadimplência: {taxa*100:.1f}%, Ticket médio: R${r['ticket_medio']:.2f}",
        })
    return results


async def generate_insights() -> dict:
    metrics = get_metrics()
    anomalias = await detect_anomalies()

    with get_db() as conn:
        repo = TransactionRepository(conn)
        top5 = repo.get_top_by_value(limit=5)
        clients_stats = repo.get_stats_by_client()

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
        "maiores_transacoes": top5,
        "stats_por_cliente": clients_stats,
        "projecao_fluxo": metrics.get("projecao_fluxo", []),
    }

    fallback_insights = [{
        "titulo": "Dados carregados com sucesso",
        "descricao": (
            f"Total de {metrics['total_transacoes']} transações. "
            f"Receita total: R${metrics['receita_total']:,.2f}. "
            f"Taxa de inadimplência: {metrics['taxa_inadimplencia']}%."
        ),
        "tipo": "tendencia",
        "severidade": "baixa",
    }]
    local_scores = _local_client_scores(clients_stats)

    if not settings.deepseek_api_key:
        return {"insights": fallback_insights, "anomalias": anomalias, "score_clientes": local_scores}

    client = AsyncOpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url)
    try:
        resp = await client.chat.completions.create(
            model=settings.deepseek_model,
            response_format={"type": "json_object"},   # structured output
            messages=[
                {"role": "system", "content": INSIGHTS_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
            ],
            temperature=0.3,
            max_tokens=2048,
        )
        raw = resp.choices[0].message.content.strip()
        # Pydantic validates and coerces all enum fields
        parsed = LLMInsightsResponse.model_validate_json(raw)
        return {
            "insights": [i.model_dump() for i in parsed.insights] or fallback_insights,
            "anomalias": anomalias,
            "score_clientes": [s.model_dump() for s in parsed.score_clientes] or local_scores,
        }
    except Exception as exc:
        logger.exception("Insights generation falhou: %s", exc)
        return {"insights": fallback_insights, "anomalias": anomalias, "score_clientes": local_scores}
