"""
Anomaly detection with IQR (Interquartile Range) instead of Z-score.

Rationale: financial data is right-skewed — Z-score assumes Gaussian distribution,
which causes high false-negative rates on leptokurtic/skewed value distributions.
IQR is a non-parametric, rank-based estimator robust to outliers by construction.
"""
import json
import logging
from collections import defaultdict
import numpy as np
from openai import AsyncOpenAI
from app.db import get_db
from app.config import settings
from app.repositories.transaction_repository import TransactionRepository

logger = logging.getLogger(__name__)

ANOMALY_SYSTEM_PROMPT = """Você é um analista de risco financeiro. Analise as transações anômalas detectadas e forneça uma contextualização objetiva para cada uma.
Retorne APENAS um JSON válido no formato: {"anomalias": [{"transacao_id": "...", "motivo": "...", "score": 0.XX}]}"""


def _iqr_anomalies_by_client(records: list[dict]) -> list[dict]:
    """
    IQR-based detection per client group.
    A transaction is anomalous if valor > Q3 + 1.5 * IQR.
    Score is proportional to how far above the fence the value is.
    """
    client_groups: defaultdict[str, list[dict]] = defaultdict(list)
    for r in records:
        client_groups[r["cliente"]].append(r)

    anomalies: list[dict] = []
    for cliente, group in client_groups.items():
        if len(group) < 4:          # IQR needs at least 4 observations
            continue
        vals = np.array([r["valor"] for r in group])
        q1, q3 = np.percentile(vals, [25, 75])
        iqr = q3 - q1
        if iqr == 0:
            continue                # all values identical — skip
        upper_fence = q3 + 1.5 * iqr

        for r in group:
            if r["valor"] > upper_fence:
                excess = r["valor"] - upper_fence
                # Normalize score: 0→fence, 1→fence + 3*IQR
                score = round(min(excess / (3 * iqr), 1.0), 3)
                anomalies.append({
                    "transacao_id": r["id"],
                    "motivo": (
                        f"Valor R${r['valor']:.2f} excede cerca IQR do cliente {cliente} "
                        f"(Q3+1.5×IQR = R${upper_fence:.2f}, IQR = R${iqr:.2f})"
                    ),
                    "score": score,
                    "_raw": r,
                })
    return anomalies


def _high_value_overdue(records: list[dict], existing_ids: set[str]) -> list[dict]:
    """Flag overdue transactions above the global P75 value."""
    all_vals = [r["valor"] for r in records]
    if not all_vals:
        return []
    p75 = float(np.percentile(all_vals, 75))
    result = []
    for r in records:
        if r["status"] == "atrasado" and r["valor"] > p75 and r["id"] not in existing_ids:
            score = round(min(r["valor"] / (p75 * 2), 1.0), 3)
            result.append({
                "transacao_id": r["id"],
                "motivo": f"Cobrança atrasada de alto valor (R${r['valor']:.2f} > P75 = R${p75:.2f})",
                "score": score,
                "_raw": r,
            })
    return result


async def detect_anomalies() -> list[dict]:
    """Full pipeline: IQR detection → high-value overdue → LLM enrichment."""
    with get_db() as conn:
        repo = TransactionRepository(conn)
        records = repo.get_all_raw()

    if not records:
        return []

    # ── Statistical detection ─────────────────────────────────────────────────
    anomalies = _iqr_anomalies_by_client(records)
    existing_ids = {a["transacao_id"] for a in anomalies}
    anomalies += _high_value_overdue(records, existing_ids)

    # Top 10 by score
    anomalies = sorted(anomalies, key=lambda x: x["score"], reverse=True)[:10]

    if not anomalies:
        return []

    clean = [{"transacao_id": a["transacao_id"], "motivo": a["motivo"], "score": a["score"]}
             for a in anomalies]

    if not settings.deepseek_api_key:
        return clean

    # ── LLM enrichment with structured output ────────────────────────────────
    client = AsyncOpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url)
    payload = [
        {
            "transacao_id": a["transacao_id"],
            "cliente": a["_raw"]["cliente"],
            "valor": a["_raw"]["valor"],
            "status": a["_raw"]["status"],
            "descricao": a["_raw"]["descricao"],
            "motivo_estatistico": a["motivo"],
        }
        for a in anomalies
    ]
    try:
        resp = await client.chat.completions.create(
            model=settings.deepseek_model,
            response_format={"type": "json_object"},   # structured output
            messages=[
                {"role": "system", "content": ANOMALY_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0,
            max_tokens=1024,
        )
        raw = resp.choices[0].message.content.strip()
        parsed = json.loads(raw)
        enriched = parsed.get("anomalias", clean)
        # Validate shape — fallback to statistical if LLM mangled it
        if isinstance(enriched, list) and all("transacao_id" in e for e in enriched):
            return enriched
    except Exception as exc:
        logger.warning("Anomaly LLM enrichment falhou: %s", exc)

    return clean
