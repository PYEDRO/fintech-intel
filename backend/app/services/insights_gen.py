import json
import logging
from openai import AsyncOpenAI
from app.config import settings
from app.db import get_db
from app.services.metrics_engine import get_metrics
from app.services.anomaly import detect_anomalies

logger = logging.getLogger(__name__)

INSIGHTS_SYSTEM_PROMPT = """Você é um analista financeiro sênior. Analise as métricas fornecidas e gere insights acionáveis.
Para cada insight, forneça:
- Título curto e direto
- Descrição com dados concretos (valores, percentuais)
- Classificação: "oportunidade", "risco" ou "tendencia"
- Severidade: "alta", "media" ou "baixa"
Foque em:
- Concentração de receita (dependência de poucos clientes)
- Padrões de inadimplência (clientes ou períodos problemáticos)
- Tendências temporais (crescimento, sazonalidade)
- Oportunidades de upsell ou cross-sell
Responda APENAS com JSON válido no formato:
{"insights": [...], "score_clientes": [...]}
Onde insights tem campos: titulo, descricao, tipo, severidade
E score_clientes tem campos: cliente, score (0-10), risco (alto/medio/baixo), motivo"""


async def generate_insights() -> dict:
    """Compute metrics + sample data → LLM → structured insights + client scores."""
    metrics = get_metrics()
    anomalias = await detect_anomalies()

    # Top 5 highest transactions
    with get_db() as conn:
        top5 = conn.execute(
            "SELECT id, cliente, valor, status, descricao FROM transacoes ORDER BY valor DESC LIMIT 5"
        ).fetchall()
        clients_stats = conn.execute(
            """
            SELECT cliente,
                   COUNT(*) AS total,
                   SUM(CASE WHEN status='pago' THEN valor ELSE 0 END) AS receita,
                   SUM(CASE WHEN status='atrasado' THEN 1 ELSE 0 END) AS atrasadas,
                   AVG(valor) AS ticket_medio
            FROM transacoes GROUP BY cliente
            """
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

    fallback_insights = [
        {
            "titulo": "Dados carregados com sucesso",
            "descricao": f"Total de {metrics['total_transacoes']} transações. Receita total: R${metrics['receita_total']:,.2f}. Taxa de inadimplência: {metrics['taxa_inadimplencia']}%.",
            "tipo": "tendencia",
            "severidade": "baixa",
        }
    ]

    if not settings.deepseek_api_key:
        return {"insights": fallback_insights, "anomalias": anomalias, "score_clientes": _compute_client_scores_local(clients_stats)}

    client = AsyncOpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url)
    try:
        resp = await client.chat.completions.create(
            model=settings.deepseek_model,
            messages=[
                {"role": "system", "content": INSIGHTS_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
            ],
            temperature=0.3,
            max_tokens=2048,
        )
        raw = resp.choices[0].message.content.strip()
        if "```" in raw:
            raw = raw.split("```")[1].lstrip("json").strip()
        result = json.loads(raw)
        return {
            "insights": result.get("insights", fallback_insights),
            "anomalias": anomalias,
            "score_clientes": result.get("score_clientes", _compute_client_scores_local(clients_stats)),
        }
    except Exception as exc:
        logger.exception("Insights generation falhou: %s", exc)
        return {
            "insights": fallback_insights,
            "anomalias": anomalias,
            "score_clientes": _compute_client_scores_local(clients_stats),
        }


def _compute_client_scores_local(clients_stats) -> list[dict]:
    """Fallback: compute client health scores locally without LLM."""
    results = []
    for r in clients_stats:
        total = r["total"] or 1
        inadimplencia_rate = r["atrasadas"] / total
        ticket = r["ticket_medio"] or 0
        # Simple heuristic score 0-10
        score = max(0.0, 10.0 - inadimplencia_rate * 20)
        risco = "alto" if score < 4 else ("medio" if score < 7 else "baixo")
        results.append({
            "cliente": r["cliente"],
            "score": round(score, 1),
            "risco": risco,
            "motivo": f"Taxa inadimplência: {inadimplencia_rate*100:.1f}%, Ticket médio: R${ticket:.2f}",
        })
    return results
