import json
import logging

import numpy as np
from openai import AsyncOpenAI, APIStatusError

from app.config import settings
from app.db import get_db
from app.services._llm_state import api_available, mark_api_down

logger = logging.getLogger(__name__)

ANOMALY_SYSTEM_PROMPT = (
    "Você é um analista de risco financeiro. "
    "Dado um conjunto de transações anômalas detectadas estatisticamente, "
    "forneça uma contextualização breve e objetiva para cada uma.\n"
    'Retorne APENAS um JSON array com objetos '
    '{"transacao_id": "...", "motivo": "...", "score": 0.XX}.\n'
    "Sem texto adicional."
)


async def detect_anomalies() -> list[dict]:
    """Z-score per client + high-value overdue detection + LLM context."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, valor, status, cliente, descricao, data FROM transacoes"
        ).fetchall()

    if not rows:
        return []

    records = [dict(r) for r in rows]

    # ── Z-score per client ────────────────────────────────────────────────────
    from collections import defaultdict
    client_values: defaultdict[str, list[float]] = defaultdict(list)
    for r in records:
        client_values[r["cliente"]].append(r["valor"])

    anomalies: list[dict] = []
    for r in records:
        vals = client_values[r["cliente"]]
        if len(vals) < 3:
            continue
        mean, std = np.mean(vals), np.std(vals)
        if std == 0:
            continue
        z = abs(r["valor"] - mean) / std
        if z > 2.0:
            anomalies.append({
                "transacao_id": r["id"],
                "motivo": (
                    f"Valor R${r['valor']:.2f} é {z:.1f}σ "
                    f"acima da média do cliente {r['cliente']} "
                    f"(R${mean:.2f})"
                ),
                "score": round(min(z / 5, 1.0), 3),
                "_raw": r,
            })

    # ── High-value overdue (> P75 of dataset) ────────────────────────────────
    all_vals = [r["valor"] for r in records]
    p75 = float(np.percentile(all_vals, 75))
    for r in records:
        if r["status"] == "atrasado" and r["valor"] > p75:
            existing_ids = {a["transacao_id"] for a in anomalies}
            if r["id"] not in existing_ids:
                anomalies.append({
                    "transacao_id": r["id"],
                    "motivo": (
                        f"Transação atrasada de alto valor "
                        f"(R${r['valor']:.2f} > P75 R${p75:.2f})"
                    ),
                    "score": round(min(r["valor"] / (p75 * 2), 1.0), 3),
                    "_raw": r,
                })

    # Take top 10 by score
    anomalies = sorted(anomalies, key=lambda x: x["score"], reverse=True)[:10]

    if not anomalies or not settings.llm_api_key or not api_available():
        return [
            {
                "transacao_id": a["transacao_id"],
                "motivo": a["motivo"],
                "score": a["score"],
            }
            for a in anomalies
        ]

    # ── LLM contextualização ─────────────────────────────────────────────────
    client = AsyncOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        timeout=8.0,
    )
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
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": ANOMALY_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0,
            max_tokens=1024,
        )
        raw = resp.choices[0].message.content.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        llm_results = json.loads(raw)
        # Validate minimal shape
        return [
            {
                "transacao_id": str(item.get("transacao_id", "")),
                "motivo": str(item.get("motivo", "")),
                "score": float(item.get("score", 0.5)),
            }
            for item in llm_results
            if isinstance(item, dict)
        ]
    except APIStatusError as exc:
        if exc.status_code in (400, 401, 402, 403, 404):
            mark_api_down(f"HTTP {exc.status_code} — {exc.message}")
        else:
            logger.warning("LLM anomaly falhou: %s — usando fallback estatístico.", exc)
    except Exception as exc:
        logger.warning("LLM anomaly contextualização falhou: %s — usando fallback estatístico.", exc)

    # Fallback: return statistical results without LLM enrichment
    return [
        {
            "transacao_id": a["transacao_id"],
            "motivo": a["motivo"],
            "score": a["score"],
        }
        for a in anomalies
    ]
