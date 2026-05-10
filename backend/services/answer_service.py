"""LLM answer generation for RAG chat — delegates to the configured provider."""

import logging
from pathlib import Path
from typing import AsyncGenerator

from core.config import config
from services.providers import get_llm_provider
from services.providers.base import (
    ProviderAuthError,
    ProviderConnectionError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT: str | None = None


def _get_system_prompt() -> str:
    global _SYSTEM_PROMPT
    if _SYSTEM_PROMPT is not None:
        return _SYSTEM_PROMPT
    path = Path(config.SYSTEM_PROMPT_PATH)
    if not path.is_file():
        raise FileNotFoundError(
            f"System prompt file not found at {path} "
            f"(SYSTEM_PROMPT_PATH={config.SYSTEM_PROMPT_PATH!r})."
        )
    _SYSTEM_PROMPT = path.read_text(encoding="utf-8").strip()
    return _SYSTEM_PROMPT

LLM_MSG_MISSING_API_KEY = (
    "LLM service is not available: API key is missing or not configured."
)
LLM_MSG_INVALID_API_KEY = "LLM request failed: invalid or unauthorized API key."
LLM_MSG_RATE_LIMIT = (
    "LLM request failed: rate limit or quota exceeded. Please try again later."
)
LLM_MSG_TIMEOUT = (
    "LLM request failed: the service timed out or could not be reached."
)
LLM_MSG_UNEXPECTED = "LLM request failed due to an unexpected error."


def _msg_missing_api_key() -> str:
    return LLM_MSG_MISSING_API_KEY


def _msg_invalid_api_key() -> str:
    return LLM_MSG_INVALID_API_KEY


def _msg_rate_limit() -> str:
    return LLM_MSG_RATE_LIMIT


def _msg_timeout_or_connection() -> str:
    return LLM_MSG_TIMEOUT


def _msg_unexpected() -> str:
    return LLM_MSG_UNEXPECTED


def _api_key_present() -> bool:
    """Check whether the active provider has credentials available."""
    provider = config.LLM_PROVIDER
    if provider == "gemini":
        key = config.GEN_AI_KEY
    elif provider == "openai":
        key = config.OPENAI_API_KEY
    else:
        # Ollama typically needs no key.
        return True
    return key is not None and str(key).strip() != ""


async def generate_answer(question: str, context: str) -> str:
    """
    Generate an answer using the configured LLM provider.

    Error classification is provider-agnostic: providers raise common
    exceptions (ProviderRateLimitError, etc.) and this function maps
    them to user-facing messages.
    """
    contents = f"CONTEXT:\n{context}\n\nQUESTION:\n{question}"

    if not _api_key_present():
        logger.error(
            "LLM cannot run: API key is missing or empty for provider %s",
            config.LLM_PROVIDER,
            extra={"error_type": "MissingAPIKey"},
        )
        return _msg_missing_api_key()

    try:
        provider = get_llm_provider()
        answer = await provider.generate(
            contents,
            system_instruction=_get_system_prompt(),
            temperature=config.LLM_TEMPERATURE,
            max_output_tokens=config.LLM_MAX_OUTPUT_TOKENS,
        )
        logger.info("Answer generated successfully")
        return answer

    except ProviderRateLimitError as e:
        logger.error(
            "LLM rate limit or quota (%s): %s",
            type(e).__name__,
            e,
            extra={"error_type": type(e).__name__},
        )
        return _msg_rate_limit()

    except ProviderAuthError as e:
        logger.error(
            "LLM API key rejected or unauthorized (%s): %s",
            type(e).__name__,
            e,
            extra={"error_type": type(e).__name__},
        )
        return _msg_invalid_api_key()

    except ProviderTimeoutError as e:
        logger.error(
            "LLM request timeout (%s): %s",
            type(e).__name__,
            e,
            exc_info=True,
            extra={"error_type": type(e).__name__},
        )
        return _msg_timeout_or_connection()

    except ProviderConnectionError as e:
        logger.error(
            "LLM connection error (%s): %s",
            type(e).__name__,
            e,
            exc_info=True,
            extra={"error_type": type(e).__name__},
        )
        return _msg_timeout_or_connection()

    except Exception as e:
        logger.error(
            "LLM unexpected error (%s): %s",
            type(e).__name__,
            e,
            exc_info=True,
            extra={"error_type": type(e).__name__},
        )
        return _msg_unexpected()

async def generate_answer_stream(question: str, context: str) -> AsyncGenerator[str, None]:
    """
    Generate an answer token-by-token using the configured LLM provider.

    Error classification is provider-agnostic: providers raise common
    exceptions (ProviderRateLimitError, etc.) and this function maps
    them to user-facing messages.
    """
    contents = f"CONTEXT:\n{context}\n\nQUESTION:\n{question}"

    if not _api_key_present():
        logger.error(
            "LLM cannot run: API key is missing or empty for provider %s",
            config.LLM_PROVIDER,
            extra={"error_type": "MissingAPIKey"},
        )
        yield _msg_missing_api_key()
        return

    try:
        provider = get_llm_provider()
        async for chunk in provider.generate_stream(
            contents,
            system_instruction=_get_system_prompt(),
            temperature=config.LLM_TEMPERATURE,
            max_output_tokens=config.LLM_MAX_OUTPUT_TOKENS,
        ):
            yield chunk

        logger.info("Answer stream generated successfully")

    except ProviderRateLimitError as e:
        logger.error(
            "LLM rate limit or quota (%s): %s",
            type(e).__name__,
            e,
            extra={"error_type": type(e).__name__},
        )
        yield _msg_rate_limit()

    except ProviderAuthError as e:
        logger.error(
            "LLM API key rejected or unauthorized (%s): %s",
            type(e).__name__,
            e,
            extra={"error_type": type(e).__name__},
        )
        yield _msg_invalid_api_key()

    except ProviderTimeoutError as e:
        logger.error(
            "LLM request timeout (%s): %s",
            type(e).__name__,
            e,
            exc_info=True,
            extra={"error_type": type(e).__name__},
        )
        yield _msg_timeout_or_connection()

    except ProviderConnectionError as e:
        logger.error(
            "LLM connection error (%s): %s",
            type(e).__name__,
            e,
            exc_info=True,
            extra={"error_type": type(e).__name__},
        )
        yield _msg_timeout_or_connection()

    except Exception as e:
        logger.error(
            "LLM unexpected error (%s): %s",
            type(e).__name__,
            e,
            exc_info=True,
            extra={"error_type": type(e).__name__},
        )
        yield _msg_unexpected()

