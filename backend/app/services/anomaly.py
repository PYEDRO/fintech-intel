import json
import logging
from collections import defaultdict

import numpy as np
from openai import AsyncOpenAI

from app.config import settings
from app.db import get_db

logger = logging.getLogger(__name__)

ANOMALY_SYSTEM_PROMPT = (
    "Você é um analista de risco financeiro. Dado um conjunto de transações anômalas"
    " detectadas estatisticamente, forneça uma contextualização breve e objetiva para"
    " cada uma.\n"
    'Retorne APENAS um JSON array com objetos {"transacao_id": "...", "motivo": "...",'
    ' "score": 0.XX}.\nSem texto adicional.'
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
            motivo = (
                f"Valor R${r['valor']:.2f} é {z:.1f}σ acima da média"
                f" do cliente {r['cliente']} (R${mean:.2f})"
            )
            anomalies.append({
                "transacao_id": r["id"],
                "motivo": motivo,
                "score": round(min(z / 5, 1.0), 3),
                "_raw": r,
            })

    # ── High-value overdue (> P75 of dataset) ────────────────────────────────
    all_vals = [r["valor"] for r in records]
    p75 = float(np.percentile(all_vals, 75))
    for r in records:
        if r["status"] == "atrasado" and r["valor"] > p75:
            # avoid duplicating
            existing_ids = {a["transacao_id"] for a in anomalies}
            if r["id"] not in existing_ids:
                motivo = (
                    f"Transação atrasada de alto valor"
                    f" (R${r['valor']:.2f} > P75 R${p75:.2f})"
                )
                anomalies.append({
                    "transacao_id": r["id"],
                    "motivo": motivo,
                    "score": round(min(r["valor"] / (p75 * 2), 1.0), 3),
                    "_raw": r,
                })

    # Take top 10 by score
    anomalies = sorted(anomalies, key=lambda x: x["score"], reverse=True)[:10]

    if not anomalies or not settings.deepseek_api_key:
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
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
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
            model=settings.deepseek_model,
            messages=[
                {"role": "system", "content": ANOMALY_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0,
            max_tokens=1024,
        )
        raw = resp.choices[0].message.content.strip()
        if "```" in raw:
            raw = raw.split("```")[1].lstrip("json").strip()
        enriched = json.loads(raw)
        return enriched
    except Exception as exc:
        logger.warning("Anomaly LLM enrichment falhou: %s", exc)
        return [
            {
                "transacao_id": a["transacao_id"],
                "motivo": a["motivo"],
                "score": a["score"],
            }
            for a in anomalies
        ]
