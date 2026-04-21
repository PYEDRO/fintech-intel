"""
Circuit breaker com time-based reset para chamadas LLM.

Quando a API retorna 402/401 (saldo insuficiente ou chave inválida),
marca como indisponível e aguarda RETRY_INTERVAL segundos antes de tentar
novamente — evita flood de requests enquanto o saldo está zerado, mas
recupera automaticamente após recarga de créditos sem restart do container.

Política:
  - 402/401 → circuit abre, retry após RETRY_INTERVAL (padrão: 1800s / 30min)
  - Outros erros HTTP → não abrem o circuit (podem ser transientes)
  - Reset manual: chamar reset_circuit()
"""
import logging
import time

logger = logging.getLogger(__name__)

# Intervalo de retry após 402/401 (segundos). Ajuste via variável de ambiente
# CIRCUIT_BREAKER_RETRY se necessário.
RETRY_INTERVAL: int = 300  # 5 minutos

_api_available: bool = True
_down_reason: str = ""
_down_since: float = 0.0   # epoch timestamp do momento em que o circuit abriu


def api_available() -> bool:
    """
    Retorna True se a API LLM está disponível para chamadas.

    Se o circuit está aberto mas o RETRY_INTERVAL já passou,
    fecha automaticamente o circuit (half-open → probe na próxima chamada).
    """
    global _api_available, _down_since, _down_reason

    if _api_available:
        return True

    elapsed = time.monotonic() - _down_since
    if elapsed >= RETRY_INTERVAL:
        _api_available = True
        _down_reason = ""
        _down_since = 0.0
        logger.info(
            "⚡ Circuit breaker resetado após %.0fs — próxima chamada ao LLM "
            "fará probe na API.",
            elapsed,
        )
        return True

    return False


def mark_api_down(reason: str) -> None:
    """
    Abre o circuit breaker.

    Idempotente durante a janela de cooldown — cada abertura reinicia o timer,
    o que é correto: cada nova falha 402 posterga o próximo retry.
    """
    global _api_available, _down_reason, _down_since
    first_open = _api_available
    _api_available = False
    _down_reason = reason
    _down_since = time.monotonic()

    if first_open:
        logger.warning(
            "⚡ LLM API desabilitada por circuit breaker: %s. "
            "Fallback rule-based ativo. Retry automático em %ds.",
            reason,
            RETRY_INTERVAL,
        )
    else:
        logger.debug("Circuit breaker já aberto — timer reiniciado: %s", reason)


def reset_circuit() -> None:
    """Reset manual do circuit breaker (útil em testes ou endpoint de admin)."""
    global _api_available, _down_reason, _down_since
    _api_available = True
    _down_reason = ""
    _down_since = 0.0
    logger.info("⚡ Circuit breaker resetado manualmente.")


def api_down_reason() -> str:
    return _down_reason
