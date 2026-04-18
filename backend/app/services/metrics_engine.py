"""
Metrics engine: SQL aggregations via TransactionRepository + Holt ETS projection.

Projection uses Holt's linear (double exponential smoothing) instead of naive
polyfit(deg=1), which is sensitive to outlier months and seasonal spikes.
Holt adapts the level and trend estimates at each step, producing more stable forecasts.
"""
import logging
import numpy as np
from typing import Optional
from app.db import get_db
from app.repositories.transaction_repository import TransactionRepository

logger = logging.getLogger(__name__)


def _build_where(
    start_date: Optional[str],
    end_date: Optional[str],
    cliente: Optional[str],
) -> tuple[str, list]:
    clauses, params = [], []
    if start_date:
        clauses.append("data >= ?")
        params.append(start_date)
    if end_date:
        clauses.append("data <= ?")
        params.append(end_date)
    if cliente:
        clauses.append("cliente = ?")
        params.append(cliente)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def _holt_projection(monthly_revenue: list[float], steps: int = 3) -> list[float]:
    """
    Holt's linear exponential smoothing (level + trend).
    α controls level smoothing, β controls trend smoothing.
    Chosen values (0.4, 0.2) give moderate responsiveness without overfitting.
    """
    if len(monthly_revenue) < 2:
        return []

    alpha, beta = 0.4, 0.2
    y = monthly_revenue

    # Initialize
    level = y[0]
    trend = y[1] - y[0]

    for val in y[1:]:
        prev_level = level
        level = alpha * val + (1 - alpha) * (prev_level + trend)
        trend = beta * (level - prev_level) + (1 - beta) * trend

    return [max(0.0, round(level + (i + 1) * trend, 2)) for i in range(steps)]


def get_metrics(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    cliente: Optional[str] = None,
) -> dict:
    where, params = _build_where(start_date, end_date, cliente)

    with get_db() as conn:
        repo = TransactionRepository(conn)

        agg = repo.get_aggregates(where, params)
        total = agg["total_transacoes"] or 1
        atrasadas = agg["atrasadas"] or 0
        taxa_inadimplencia = round((atrasadas / total) * 100, 2)

        evolucao = repo.get_monthly_evolution(where, params)
        por_cliente = repo.get_by_client(where, params)
        por_categoria = repo.get_by_category(where, params)
        last6 = repo.get_last_n_months_revenue(n=6, where=where, params=params)

    # ── Cash flow projection via Holt ETS ────────────────────────────────────
    projection = []
    if len(last6) >= 2:
        revenues = [r["receita"] for r in last6]
        projected_values = _holt_projection(revenues, steps=3)
        last_mes = last6[-1]["mes"]
        from datetime import datetime
        last_dt = datetime.strptime(last_mes, "%Y-%m")
        for i, proj_val in enumerate(projected_values, start=1):
            month = last_dt.month + i
            year = last_dt.year + (month - 1) // 12
            month = ((month - 1) % 12) + 1
            projection.append({"mes": f"{year:04d}-{month:02d}", "receita_projetada": proj_val})

    return {
        "receita_total": round(agg["receita_total"], 2),
        "ticket_medio": round(agg["ticket_medio"], 2),
        "taxa_inadimplencia": taxa_inadimplencia,
        "total_transacoes": agg["total_transacoes"],
        "transacoes_paidas": agg["pagas"],
        "transacoes_pagas": agg["pagas"],
        "transacoes_pendentes": agg["pendentes"],
        "transacoes_atrasadas": atrasadas,
        "evolucao_mensal": [
            {"mes": r["mes"], "receita": round(r["receita"], 2), "count": r["count"]}
            for r in evolucao
        ],
        "por_cliente": [
            {"cliente": r["cliente"], "receita": round(r["receita"], 2), "count": r["count"]}
            for r in por_cliente
        ],
        "por_categoria": [
            {"categoria": r["categoria"], "receita": round(r["receita"], 2), "count": r["count"]}
            for r in por_categoria
        ],
        "por_status": {
            "pago": agg["pagas"],
            "pendente": agg["pendentes"],
            "atrasado": atrasadas,
        },
        "projecao_fluxo": projection,
    }
