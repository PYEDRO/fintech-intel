"""
LLM-based transaction classifier using DeepSeek with structured JSON output.

Uses response_format={"type": "json_object"} to guarantee valid JSON,
then validates against a Pydantic model — eliminating fragile string parsing.
"""
import json
import logging
from typing import List
from pydantic import BaseModel, field_validator
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
_VALID_SET = set(CATEGORIES)
FALLBACK = "Não Classificado"

SYSTEM_PROMPT = f"""Você é um classificador de transações financeiras.
Classifique cada transação em EXATAMENTE UMA das categorias a seguir:
{chr(10).join(f'- {c}' for c in CATEGORIES)}

Responda APENAS com um JSON no formato:
{{"categories": ["categoria1", "categoria2", ...]}}

O array deve ter exatamente o mesmo número de elementos que a lista de entrada."""


# ── Pydantic response schema ──────────────────────────────────────────────────

class ClassifierResponse(BaseModel):
    categories: List[str]

    @field_validator("categories", mode="before")
    @classmethod
    def validate_categories(cls, v: list) -> list:
        return [c if c in _VALID_SET else FALLBACK for c in v]


# ── LLM call ──────────────────────────────────────────────────────────────────

def _get_client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=settings.deepseek_api_key, base_url=settings.deepseek_base_url)


async def _classify_batch(descriptions: List[str]) -> List[str]:
    if not settings.deepseek_api_key:
        return [FALLBACK] * len(descriptions)

    numbered = "\n".join(f"{i+1}. {d}" for i, d in enumerate(descriptions))
    user_msg = f"Classifique exatamente {len(descriptions)} descrições:\n{numbered}"

    try:
        resp = await _get_client().chat.completions.create(
            model=settings.deepseek_model,
            response_format={"type": "json_object"},   # guarantees valid JSON
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0,
            max_tokens=512,
        )
        raw = resp.choices[0].message.content.strip()
        parsed = ClassifierResponse.model_validate_json(raw)

        if len(parsed.categories) != len(descriptions):
            logger.warning(
                "Classifier length mismatch: expected %d, got %d",
                len(descriptions), len(parsed.categories),
            )
            # Pad or truncate to match input size
            result = parsed.categories[:len(descriptions)]
            result += [FALLBACK] * max(0, len(descriptions) - len(result))
            return result

        return parsed.categories

    except Exception as exc:
        logger.warning("Classificação falhou para batch (%d items): %s", len(descriptions), exc)
        return [FALLBACK] * len(descriptions)


async def classify_descriptions_batch(descriptions: List[str]) -> List[str]:
    results: List[str] = []
    bs = settings.classifier_batch_size
    for i in range(0, len(descriptions), bs):
        batch = descriptions[i : i + bs]
        results.extend(await _classify_batch(batch))
    return results
