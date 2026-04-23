"""Abstract base classes and common exceptions for LLM & embedding providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


# ---------------------------------------------------------------------------
# Common provider exceptions
# ---------------------------------------------------------------------------
# Each provider catches its own SDK-specific errors and re-raises as one of
# these.  The service layer (answer_service, embedding_service) catches only
# these common types — it never needs to know which provider is active.
# ---------------------------------------------------------------------------


class ProviderError(Exception):
    """Catch-all for provider errors that don't fit a more specific category."""


class ProviderRateLimitError(ProviderError):
    """The provider rejected the request due to rate limiting or quota."""


class ProviderAuthError(ProviderError):
    """The provider rejected the request due to invalid or missing credentials."""


class ProviderTimeoutError(ProviderError):
    """The request to the provider timed out."""


class ProviderConnectionError(ProviderError):
    """Could not reach the provider (network error, DNS failure, etc.)."""


# ---------------------------------------------------------------------------
# Abstract base classes
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Known embedding dimensions
# ---------------------------------------------------------------------------
# Maps model names to their output vector dimension.  Used by config to
# auto-detect EMBEDDING_DIM so the DB schema matches the selected model.

KNOWN_EMBEDDING_DIMS: dict[str, int] = {
    # Gemini
    "models/gemini-embedding-001": 3072,
    # OpenAI
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
    # Ollama
    "nomic-embed-text": 768,
    "mxbai-embed-large": 1024,
    "all-minilm": 384,
    "snowflake-arctic-embed": 1024,
}

# Default embedding model per provider (must match the defaults in each
# provider's module so the dimension lookup stays consistent).
_DEFAULT_EMBEDDING_MODELS: dict[str, str] = {
    "gemini": "models/gemini-embedding-001",
    "openai": "text-embedding-3-small",
    "ollama": "nomic-embed-text",
}


# ---------------------------------------------------------------------------
# Abstract base classes
# ---------------------------------------------------------------------------


class EmbeddingProvider(ABC):
    """Common interface for text-embedding implementations."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""

    @property
    def embedding_dim(self) -> int:
        """Return the output vector dimension for the configured model.

        This is the authoritative source consulted by
        ``core.config.get_embedding_dim()`` for pgvector column sizing.
        Default implementation looks up ``self._model`` in
        ``KNOWN_EMBEDDING_DIMS``; subclasses may override to query the
        model server at runtime.  Note that the DB schema is frozen at
        module import time, so any runtime-discovered dimension must
        agree with it.
        """
        model: str | None = getattr(self, "_model", None)
        if model:
            dim = KNOWN_EMBEDDING_DIMS.get(model)
            if dim:
                return dim
            # Handle provider-prefixed names like "openai/text-embedding-3-small".
            if "/" in model:
                dim = KNOWN_EMBEDDING_DIMS.get(model.rsplit("/", 1)[1])
                if dim:
                    return dim
            raise ValueError(
                f"Unknown embedding model {model!r}. "
                f"Set EMBEDDING_DIM in the environment or add the model to "
                f"KNOWN_EMBEDDING_DIMS in services/providers/base.py."
            )
        raise ValueError(
            "Cannot resolve embedding dimension: provider has no _model set. "
            "Set EMBEDDING_DIM in the environment or ensure the provider sets _model."
        )


class LLMProvider(ABC):
    """Common interface for LLM text-generation implementations."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        system_instruction: str,
        temperature: float,
        max_output_tokens: int,
        extra_params: dict[str, Any] | None = None,
    ) -> str:
        """Generate a text response for the given prompt.

        Parameters
        ----------
        extra_params
            Optional provider-specific parameters (e.g. top_p, stop
            sequences).  Each provider maps relevant keys to its SDK
            format and ignores unrecognised keys.
        """
