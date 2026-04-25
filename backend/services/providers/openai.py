"""OpenAI provider implementations."""

from __future__ import annotations

import logging
from typing import Any

import openai

from core.config import config
from services.providers.base import (
    EmbeddingProvider,
    LLMProvider,
    ProviderAuthError,
    ProviderConnectionError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
_DEFAULT_LLM_MODEL = "gpt-4o-mini"


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


def _classify_openai_error(
    exc: openai.APIError,
) -> ProviderError:
    """Map an OpenAI SDK exception to the appropriate common provider exception.

    The ``openai`` SDK already provides typed exception classes, so this is
    much simpler than the Gemini mapper — we match on class rather than
    inspecting status codes or message strings.
    """
    # Order matters: subclasses must be checked before their parents.
    # APITimeoutError -> APIConnectionError -> APIError, so check timeout first.
    if isinstance(exc, openai.APITimeoutError):
        return ProviderTimeoutError(str(exc))
    if isinstance(exc, openai.APIConnectionError):
        return ProviderConnectionError(str(exc))
    if isinstance(exc, openai.RateLimitError):
        return ProviderRateLimitError(str(exc))
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return ProviderAuthError(str(exc))
    # BadRequestError, NotFoundError, InternalServerError, etc.
    return ProviderError(str(exc))


# ---------------------------------------------------------------------------
# Embedding provider
# ---------------------------------------------------------------------------


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """Embedding provider backed by the OpenAI API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._model = model or config.EMBEDDING_MODEL or _DEFAULT_EMBEDDING_MODEL
        self._client = openai.AsyncOpenAI(
            api_key=api_key or config.OPENAI_API_KEY,
            base_url=base_url or config.OPENAI_BASE_URL,
            timeout=float(config.EMBEDDING_HTTP_TIMEOUT_SEC),
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed *texts* via the OpenAI embeddings endpoint."""
        try:
            response = await self._client.embeddings.create(
                model=self._model,
                input=texts,
            )
            return [item.embedding for item in response.data]

        except openai.APIError as exc:
            raise _classify_openai_error(exc) from exc


# ---------------------------------------------------------------------------
# LLM provider
# ---------------------------------------------------------------------------


class OpenAILLMProvider(LLMProvider):
    """LLM provider backed by the OpenAI chat completions API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._model = model or config.LLM_MODEL or _DEFAULT_LLM_MODEL
        self._client = openai.AsyncOpenAI(
            api_key=api_key or config.OPENAI_API_KEY,
            base_url=base_url or config.OPENAI_BASE_URL,
            timeout=float(config.LLM_HTTP_TIMEOUT_MS) / 1000.0,
        )

    async def generate(
        self,
        prompt: str,
        *,
        system_instruction: str,
        temperature: float,
        max_output_tokens: int,
        extra_params: dict[str, Any] | None = None,
    ) -> str:
        """Call OpenAI's chat completions endpoint."""
        try:
            create_kwargs: dict[str, Any] = {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt},
                ],
                "temperature": temperature,
                "max_tokens": max_output_tokens,
            }
            if extra_params:
                for key in ("top_p", "frequency_penalty", "presence_penalty", "stop", "seed"):
                    if key in extra_params:
                        create_kwargs[key] = extra_params[key]
            response = await self._client.chat.completions.create(**create_kwargs)
            return response.choices[0].message.content or "No response."

        except openai.APIError as exc:
            raise _classify_openai_error(exc) from exc
