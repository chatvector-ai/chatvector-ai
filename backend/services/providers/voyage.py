"""Voyage AI embedding provider implementation."""

from __future__ import annotations

import logging

import httpx

from core.config import config
from services.providers.base import (
    EmbeddingProvider,
    ProviderAuthError,
    ProviderConnectionError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)

logger = logging.getLogger(__name__)

_DEFAULT_EMBEDDING_MODEL = "voyage-3-large"
_BATCH_SIZE = 128


def _classify_http_error(exc: httpx.HTTPStatusError) -> ProviderError:
    code = exc.response.status_code
    if code == 429:
        return ProviderRateLimitError(str(exc))
    if code in (401, 403):
        return ProviderAuthError(str(exc))
    return ProviderError(str(exc))


def _classify_network_error(
    exc: httpx.TimeoutException | httpx.ConnectError | httpx.NetworkError,
) -> ProviderTimeoutError | ProviderConnectionError:
    if isinstance(exc, httpx.TimeoutException):
        return ProviderTimeoutError(str(exc))
    return ProviderConnectionError(str(exc))


class VoyageEmbeddingProvider(EmbeddingProvider):
    """Embedding provider backed by the Voyage AI REST API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._model = model or config.EMBEDDING_MODEL or _DEFAULT_EMBEDDING_MODEL
        self._api_key = api_key or config.VOYAGE_API_KEY
        self._base_url = (base_url or "https://api.voyageai.com").rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=float(config.EMBEDDING_HTTP_TIMEOUT_SEC),
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not self._api_key:
            raise ProviderAuthError("VOYAGE_API_KEY is not configured.")

        all_embeddings: list[list[float]] = []

        for batch_start in range(0, len(texts), _BATCH_SIZE):
            batch = texts[batch_start : batch_start + _BATCH_SIZE]
            try:
                response = await self._client.post(
                    "/v1/embeddings",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={"input": batch, "model": self._model},
                )
                response.raise_for_status()
                data = response.json()
                embeddings = [item["embedding"] for item in data["data"]]
                all_embeddings.extend(embeddings)

            except httpx.HTTPStatusError as exc:
                raise _classify_http_error(exc) from exc
            except (
                httpx.TimeoutException,
                httpx.ConnectError,
                httpx.NetworkError,
            ) as exc:
                raise _classify_network_error(exc) from exc

        return all_embeddings
