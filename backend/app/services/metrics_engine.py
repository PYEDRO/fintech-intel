import logging
from typing import Optional
from app.db import get_db

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


def get_metrics(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    cliente: Optional[str] = None,
) -> dict:
    where, params = _build_where(start_date, end_date, cliente)

    with get_db() as conn:
        # ── Totals ────────────────────────────────────────────────────────────
        row = conn.execute(
            f"""
            SELECT
                COALESCE(SUM(CASE WHEN status='pago' THEN valor ELSE 0 END), 0)  AS receita_total,
                COALESCE(AVG(CASE WHEN status='pago' THEN valor END), 0)          AS ticket_medio,
                COUNT(*)                                                           AS total_transacoes,
                COALESCE(SUM(CASE WHEN status='pago'      THEN 1 ELSE 0 END), 0) AS pagas,
                COALESCE(SUM(CASE WHEN status='pendente'  THEN 1 ELSE 0 END), 0) AS pendentes,
                COALESCE(SUM(CASE WHEN status='atrasado'  THEN 1 ELSE 0 END), 0) AS atrasadas
            FROM transacoes {where}
            """,
            params,
        ).fetchone()

        total = row["total_transacoes"] or 1  # avoid /0
        atrasadas = row["atrasadas"] or 0
        taxa_inadimplencia = round((atrasadas / total) * 100, 2)

        # ── Monthly evolution ─────────────────────────────────────────────────
        evolucao_rows = conn.execute(
            f"""
            SELECT
                strftime('%Y-%m', data)                                         AS mes,
                COALESCE(SUM(CASE WHEN status='pago' THEN valor ELSE 0 END), 0) AS receita,
                COUNT(*)                                                         AS count
            FROM transacoes {where}
            GROUP BY mes
            ORDER BY mes
            """,
            params,
        ).fetchall()

        # ── By client ─────────────────────────────────────────────────────────
        cliente_rows = conn.execute(
            f"""
            SELECT
                cliente,
                COALESCE(SUM(CASE WHEN status='pago' THEN valor ELSE 0 END), 0) AS receita,
                COUNT(*) AS count
            FROM transacoes {where}
            GROUP BY cliente
            ORDER BY receita DESC
            """,
            params,
        ).fetchall()

        # ── By category ───────────────────────────────────────────────────────
        cat_rows = conn.execute(
            f"""
            SELECT
                COALESCE(categoria, 'Não Classificado')                          AS categoria,
                COALESCE(SUM(CASE WHEN status='pago' THEN valor ELSE 0 END), 0)  AS receita,
                COUNT(*) AS count
            FROM transacoes {where}
            GROUP BY categoria
            ORDER BY receita DESC
            """,
            params,
        ).fetchall()

        # ── Cash flow projection (last 6 months linear trend) ─────────────────
        projection = _compute_projection(conn, where, params)

    return {
        "receita_total": round(row["receita_total"], 2),
        "ticket_medio": round(row["ticket_medio"], 2),
        "taxa_inadimplencia": taxa_inadimplencia,
        "total_transacoes": row["total_transacoes"],
        "transacoes_pagas": row["pagas"],
        "transacoes_pendentes": row["pendentes"],
        "transacoes_atrasadas": row["atrasadas"],
        "evolucao_mensal": [
            {"mes": r["mes"], "receita": round(r["receita"], 2), "count": r["count"]}
            for r in evolucao_rows
        ],
        "por_cliente": [
            {"cliente": r["cliente"], "receita": round(r["receita"], 2), "count": r["count"]}
            for r in cliente_rows
        ],
        "por_categoria": [
            {"categoria": r["categoria"], "receita": round(r["receita"], 2), "count": r["count"]}
            for r in cat_rows
        ],
        "por_status": {
            "pago": row["pagas"],
            "pendente": row["pendentes"],
            "atrasado": row["atrasadas"],
        },
        "projecao_fluxo": projection,
    }


def _compute_projection(conn, where: str, params: list) -> list[dict]:
    """Linear regression on last 6 months of paid revenue → 3-month forecast."""
    import numpy as np

    rows = conn.execute(
        f"""
        SELECT strftime('%Y-%m', data) AS mes,
               SUM(CASE WHEN status='pago' THEN valor ELSE 0 END) AS receita
        FROM transacoes {where}
        GROUP BY mes ORDER BY mes DESC LIMIT 6
        """,
        params,
    ).fetchall()

    if len(rows) < 2:
        return []

    rows = list(reversed(rows))
    x = np.arange(len(rows), dtype=float)
    y = np.array([r["receita"] for r in rows], dtype=float)
    coeffs = np.polyfit(x, y, 1)  # slope, intercept

    # Generate next 3 months
    from datetime import datetime
    last_mes = rows[-1]["mes"]
    last_dt = datetime.strptime(last_mes, "%Y-%m")
    projection = []
    for i in range(1, 4):
        month = last_dt.month + i
        year = last_dt.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        proj_val = max(0.0, float(np.polyval(coeffs, len(rows) - 1 + i)))
        projection.append({"mes": f"{year:04d}-{month:02d}", "receita_projetada": round(proj_val, 2)})

    return projection
