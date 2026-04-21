import json
import logging
from typing import List

from openai import AsyncOpenAI, APIStatusError

from app.config import settings
from app.services._llm_state import api_available, mark_api_down

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

# Keyword fallback — used when no LLM API key is configured.
# Keys are CATEGORIES; values are lowercase tokens matched against descricao.
_KEYWORD_MAP: dict[str, list[str]] = {
    "Assinatura Recorrente": [
        "assinatura", "recorrente", "mensal", "monthly", "subscription", "assinar",
    ],
    "Plano Premium": [
        "premium", "plano", "plan", "pro ",
    ],
    "Licença Anual": [
        "licenca", "licença", "anual", "yearly", "annual", "license", "licence",
    ],
    "Contratação Premium": [
        "contratacao", "contratação", "enterprise", "corporativo", "corporate",
    ],
    "Cobrança Recorrente": [
        "cobranca", "cobrança", "billing", "fatura", "recorrencia", "recorrência",
    ],
    "Compra Única": [
        "compra unica", "compra única", "one-time", "avulso", "pontual",
    ],
    "Serviço Avulso": [
        "servico", "serviço", "avulso", "service", "suporte", "consultoria",
    ],
}


def _classify_by_keyword(description: str) -> str:
    """Rule-based fallback classification when no LLM key is available."""
    desc_lower = description.lower()
    for category, keywords in _KEYWORD_MAP.items():
        if any(kw in desc_lower for kw in keywords):
            return category
    return "Serviço Avulso"


def _get_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        timeout=8.0,
    )


async def _classify_batch(descriptions: List[str]) -> List[str]:
    """Send one batch of descriptions to the LLM and parse categories."""
    if not settings.llm_api_key or not api_available():
        logger.info("LLM indisponível — usando fallback por keyword.")
        return [_classify_by_keyword(d) for d in descriptions]

    client = _get_client()
    numbered = "\n".join(f"{i+1}. {d}" for i, d in enumerate(descriptions))
    user_msg = f"Classifique as seguintes {len(descriptions)} descrições:\n{numbered}"

    try:
        resp = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=0,
            max_tokens=512,
        )
        raw = resp.choices[0].message.content.strip()
        if "```" in raw:
            raw = raw.split("```")[1].lstrip("json").strip()
        categories = json.loads(raw)
        if not isinstance(categories, list) or len(categories) != len(descriptions):
            raise ValueError("Unexpected response shape")
        return [c if c in CATEGORIES else "Serviço Avulso" for c in categories]
    except APIStatusError as exc:
        if exc.status_code in (401, 402, 403, 404):
            mark_api_down(f"HTTP {exc.status_code} — {exc.message}")
        else:
            logger.warning("Classificação LLM falhou: %s — usando fallback por keyword.", exc)
        return [_classify_by_keyword(d) for d in descriptions]
    except Exception as exc:
        logger.warning("Classificação LLM falhou: %s — usando fallback por keyword.", exc)
        return [_classify_by_keyword(d) for d in descriptions]


async def classify_descriptions_batch(descriptions: List[str]) -> List[str]:
    """Classify all descriptions in batches of BATCH_SIZE."""
    batch_size = settings.classifier_batch_size
    results: List[str] = []
    for i in range(0, len(descriptions), batch_size):
        batch = descriptions[i : i + batch_size]
        categories = await _classify_batch(batch)
        results.extend(categories)
    return results
