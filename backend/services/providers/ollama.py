"""Ollama provider implementations (raw httpx, no SDK)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

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

_DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"
_DEFAULT_LLM_MODEL = "llama3"


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


def _classify_http_error(exc: httpx.HTTPStatusError) -> ProviderError:
    """Map an HTTP status error from the Ollama REST API to a provider exception."""
    code = exc.response.status_code
    if code == 429:
        return ProviderRateLimitError(str(exc))
    if code in (401, 403):
        return ProviderAuthError(str(exc))
    return ProviderError(str(exc))


def _classify_network_error(
    exc: httpx.TimeoutException | httpx.ConnectError | httpx.NetworkError,
) -> ProviderTimeoutError | ProviderConnectionError:
    """Map network-level httpx exceptions to provider exceptions."""
    if isinstance(exc, httpx.TimeoutException):
        return ProviderTimeoutError(str(exc))
    return ProviderConnectionError(str(exc))


# ---------------------------------------------------------------------------
# Embedding provider
# ---------------------------------------------------------------------------


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Embedding provider backed by the Ollama REST API."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self._model = model or config.EMBEDDING_MODEL or _DEFAULT_EMBEDDING_MODEL
        self._base_url = (base_url or config.OLLAMA_BASE_URL).rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=60.0,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """POST to ``/api/embed`` for batch embedding."""
        try:
            response = await self._client.post(
                "/api/embed",
                json={"model": self._model, "input": texts},
            )
            response.raise_for_status()
            data = response.json()
            embeddings = data.get("embeddings") or data.get("embedding")
            if not embeddings:
                raise ProviderError(
                    f"Unexpected Ollama embed response shape: {list(data.keys())}"
                )
            return embeddings

        except httpx.HTTPStatusError as exc:
            raise _classify_http_error(exc) from exc
        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
            raise _classify_network_error(exc) from exc


# ---------------------------------------------------------------------------
# LLM provider
# ---------------------------------------------------------------------------


class OllamaLLMProvider(LLMProvider):
    """LLM provider backed by the Ollama REST API."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self._model = model or config.LLM_MODEL or _DEFAULT_LLM_MODEL
        self._base_url = (base_url or config.OLLAMA_BASE_URL).rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=120.0,
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
        """POST to ``/api/generate`` for non-streaming text generation."""
        try:
            options: dict[str, Any] = {
                "temperature": temperature,
                "num_predict": max_output_tokens,
            }
            if extra_params:
                for key in ("top_p", "top_k", "stop", "repeat_penalty", "seed"):
                    if key in extra_params:
                        options[key] = extra_params[key]
            response = await self._client.post(
                "/api/generate",
                json={
                    "model": self._model,
                    "prompt": prompt,
                    "system": system_instruction,
                    "stream": False,
                    "options": options,
                },
            )
            response.raise_for_status()
            return response.json().get("response", "No response.")

        except httpx.HTTPStatusError as exc:
            raise _classify_http_error(exc) from exc
        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
            raise _classify_network_error(exc) from exc
