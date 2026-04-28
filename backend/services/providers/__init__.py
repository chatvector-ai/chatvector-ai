"""Pluggable LLM & Embedding provider system.

Factory functions read ``config.LLM_PROVIDER`` / ``config.EMBEDDING_PROVIDER``
and return the matching concrete implementation.  Provider singletons are
cached at module level (kept public so tests can reset them).
"""

from __future__ import annotations

import logging

from core.config import config
from services.providers.base import EmbeddingProvider, LLMProvider

logger = logging.getLogger(__name__)

# Singletons — public so tests can reset them (same pattern as db.db_service).
# NOTE: Phase 3 will require per-tenant or per-request provider instances.
# Current singleton pattern will be replaced.
_embedding_provider: EmbeddingProvider | None = None
_llm_provider: LLMProvider | None = None


def get_embedding_provider() -> EmbeddingProvider:
    """Return singleton embedding provider based on ``EMBEDDING_PROVIDER``."""
    global _embedding_provider

    if _embedding_provider is not None:
        return _embedding_provider

    name = config.EMBEDDING_PROVIDER

    if name == "gemini":
        from services.providers.gemini import GeminiEmbeddingProvider

        _embedding_provider = GeminiEmbeddingProvider()
        logger.info("Using Gemini embedding provider")

    elif name == "openai":
        from services.providers.openai import OpenAIEmbeddingProvider

        _embedding_provider = OpenAIEmbeddingProvider()
        logger.info("Using OpenAI embedding provider")

    elif name == "ollama":
        from services.providers.ollama import OllamaEmbeddingProvider

        _embedding_provider = OllamaEmbeddingProvider()
        logger.info("Using Ollama embedding provider")

    else:
        raise ValueError(
            f"Unknown EMBEDDING_PROVIDER={name!r}. "
            f"Expected one of: gemini, openai, ollama."
        )

    return _embedding_provider


def get_llm_provider() -> LLMProvider:
    """Return singleton LLM provider based on ``LLM_PROVIDER``."""
    global _llm_provider

    if _llm_provider is not None:
        return _llm_provider

    name = config.LLM_PROVIDER

    if name == "gemini":
        from services.providers.gemini import GeminiLLMProvider

        _llm_provider = GeminiLLMProvider()
        logger.info("Using Gemini LLM provider")

    elif name == "openai":
        from services.providers.openai import OpenAILLMProvider

        _llm_provider = OpenAILLMProvider()
        logger.info("Using OpenAI LLM provider")

    elif name == "ollama":
        from services.providers.ollama import OllamaLLMProvider

        _llm_provider = OllamaLLMProvider()
        logger.info("Using Ollama LLM provider")

    else:
        raise ValueError(
            f"Unknown LLM_PROVIDER={name!r}. "
            f"Expected one of: gemini, openai, ollama."
        )

    return _llm_provider
