import json
import logging
from typing import List
from openai import AsyncOpenAI
from app.config import settings

logger = logging.getLogger(__name__)

CATEGORIES = [
    "Assinatura Recorrente",
    "Contratação Premium",
    "Licença Anual",
    "Serviço Avulso",
    "Compra Única",
    "Plano Premium",
    "Cobrança Recorrente",
]

SYSTEM_PROMPT = """Você é um classificador de transações financeiras.
Classifique cada transação em EXATAMENTE UMA categoria:
- Assinatura Recorrente
- Contratação Premium
- Licença Anual
- Serviço Avulso
- Compra Única
- Plano Premium
- Cobrança Recorrente
Responda APENAS com um JSON array no formato: ["categoria1", "categoria2", ...]
Sem explicações adicionais."""


def _get_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
    )


async def _classify_batch(descriptions: List[str]) -> List[str]:
    """Send one batch of descriptions to DeepSeek and parse categories."""
    if not settings.deepseek_api_key:
        return ["Não Classificado"] * len(descriptions)

    client = _get_client()
    numbered = "\n".join(f"{i+1}. {d}" for i, d in enumerate(descriptions))
    user_msg = f"Classifique as seguintes {len(descriptions)} descrições:\n{numbered}"

    try:
        resp = await client.chat.completions.create(
            model=settings.deepseek_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0,
            max_tokens=512,
        )
        raw = resp.choices[0].message.content.strip()
        # Extract JSON array even if wrapped in markdown
        if "```" in raw:
            raw = raw.split("```")[1].lstrip("json").strip()
        categories = json.loads(raw)
        if not isinstance(categories, list) or len(categories) != len(descriptions):
            raise ValueError("Unexpected response shape")
        return [c if c in CATEGORIES else "Não Classificado" for c in categories]
    except Exception as exc:
        logger.warning("Classificação falhou para batch: %s", exc)
        return ["Não Classificado"] * len(descriptions)


async def classify_descriptions_batch(descriptions: List[str]) -> List[str]:
    """Classify all descriptions in batches of BATCH_SIZE."""
    batch_size = settings.classifier_batch_size
    results: List[str] = []
    for i in range(0, len(descriptions), batch_size):
        batch = descriptions[i : i + batch_size]
        categories = await _classify_batch(batch)
        results.extend(categories)
    return results
