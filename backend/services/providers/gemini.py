"""Google Gemini provider implementations."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncGenerator

import httpx
from google import genai
from google.genai import types as genai_types
from google.genai.errors import APIError

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
# Helpers
# ---------------------------------------------------------------------------

# Gemini's embed_content endpoint accepts at most 100 texts per call.
_BATCH_SIZE = 100

# Default models when the user doesn't specify one via LLM_MODEL / EMBEDDING_MODEL.
_DEFAULT_EMBEDDING_MODEL = "models/gemini-embedding-001"
_DEFAULT_LLM_MODEL = "gemini-2.5-flash"


def _classify_gemini_error(exc: APIError) -> ProviderError:
    """Map a Gemini ``APIError`` to the appropriate common provider exception.

    This replicates the same classification logic that ``answer_service.py``
    used to do inline, so the granularity is preserved exactly.
    """
    code = getattr(exc, "code", None)
    status = str(getattr(exc, "status", "") or "").lower()
    msg = str(exc).lower()

    # Rate-limit / quota ---------------------------------------------------
    if code == 429 or "resource_exhausted" in status or "quota" in msg:
        return ProviderRateLimitError(str(exc))

    # Authentication / authorisation ----------------------------------------
    if code in (401, 403) or "unauthenticated" in msg or "permission_denied" in status:
        return ProviderAuthError(str(exc))

    # Invalid API key (comes back as 400 with a specific message) ----------
    if code == 400 and ("api key" in msg or "api_key" in msg or "invalid key" in msg):
        return ProviderAuthError(str(exc))

    # Everything else -------------------------------------------------------
    return ProviderError(str(exc))


def _classify_network_error(
    exc: httpx.TimeoutException
    | httpx.ConnectError
    | httpx.RemoteProtocolError
    | httpx.NetworkError
    | TimeoutError
    | ConnectionError
    | BrokenPipeError,
) -> ProviderTimeoutError | ProviderConnectionError:
    """Map network-level exceptions to provider exceptions."""
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return ProviderTimeoutError(str(exc))
    return ProviderConnectionError(str(exc))


# ---------------------------------------------------------------------------
# Embedding provider
# ---------------------------------------------------------------------------


class GeminiEmbeddingProvider(EmbeddingProvider):
    """Embedding provider backed by the Google Gemini API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self._model = model or config.EMBEDDING_MODEL or _DEFAULT_EMBEDDING_MODEL
        self._client = genai.Client(api_key=api_key or config.GEN_AI_KEY)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed *texts* in batches of at most ``_BATCH_SIZE``."""
        all_embeddings: list[list[float]] = []

        for batch_start in range(0, len(texts), _BATCH_SIZE):
            batch = texts[batch_start : batch_start + _BATCH_SIZE]
            try:
                result = await asyncio.to_thread(
                    self._client.models.embed_content,
                    model=self._model,
                    contents=batch,
                )
                all_embeddings.extend(e.values for e in result.embeddings)

            except APIError as exc:
                raise _classify_gemini_error(exc) from exc
            except (
                httpx.TimeoutException,
                httpx.ConnectError,
                httpx.RemoteProtocolError,
                httpx.NetworkError,
                TimeoutError,
                ConnectionError,
                BrokenPipeError,
            ) as exc:
                raise _classify_network_error(exc) from exc

        return all_embeddings


# ---------------------------------------------------------------------------
# LLM provider
# ---------------------------------------------------------------------------


class GeminiLLMProvider(LLMProvider):
    """LLM provider backed by the Google Gemini API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout_ms: int | None = None,
    ) -> None:
        self._model = model or config.LLM_MODEL or _DEFAULT_LLM_MODEL
        resolved_key = api_key or config.GEN_AI_KEY
        timeout = timeout_ms or config.LLM_HTTP_TIMEOUT_MS
        self._client = genai.Client(
            api_key=resolved_key,
            http_options=genai_types.HttpOptions(timeout=timeout),
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
        """Call Gemini's ``generateContent`` endpoint."""
        config_kwargs: dict[str, Any] = {
            "system_instruction": system_instruction,
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
        }
        if extra_params:
            for key in ("top_p", "top_k", "stop_sequences", "candidate_count"):
                if key in extra_params:
                    config_kwargs[key] = extra_params[key]
        gen_config = genai_types.GenerateContentConfig(**config_kwargs)

        try:
            response = await asyncio.to_thread(
                self._client.models.generate_content,
                model=self._model,
                contents=prompt,
                config=gen_config,
            )
            return response.text or "No response."

        except APIError as exc:
            raise _classify_gemini_error(exc) from exc
        except (
            httpx.TimeoutException,
            httpx.ConnectError,
            httpx.RemoteProtocolError,
            httpx.NetworkError,
            TimeoutError,
            ConnectionError,
            BrokenPipeError,
        ) as exc:
            raise _classify_network_error(exc) from exc

    async def generate_stream(
        self,
        prompt: str,
        *,
        system_instruction: str,
        temperature: float,
        max_output_tokens: int,
        extra_params: dict[str, Any] | None = None,
    ) -> AsyncGenerator[str, None]:
        """Call Gemini's ``generateContentStream`` endpoint."""
        config_kwargs: dict[str, Any] = {
            "system_instruction": system_instruction,
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
        }
        if extra_params:
            for key in ("top_p", "top_k", "stop_sequences", "candidate_count"):
                if key in extra_params:
                    config_kwargs[key] = extra_params[key]
        gen_config = genai_types.GenerateContentConfig(**config_kwargs)

        try:
            # We use an async client context for streaming if needed, but since genai client is not purely async
            # we'll run generate_content_stream in an async-friendly wrapper or just use the async methods if available.
            # wait, google-genai async methods are accessible via client.aio... Let's use self._client.aio
            # Let's check if the client exposes .aio. Wait, the non-streaming uses `asyncio.to_thread(self._client.models.generate_content...)`
            # For streaming, if there's no native async iterator we might need to wrap it.
            # Actually, `google-genai` supports `client.aio.models.generate_content_stream`. We should check if we can use it.
            # If not, we can use `asyncio.to_thread` for the initial call, and then wrap the sync iterator. But better to use `client.aio` if possible.
            # However, looking at the sync one, it's just using asyncio.to_thread because the client is synchronous.
            # Let's wrap the generator using asyncio.to_thread for next().
            
            # Actually, wait. I will just use asyncio.to_thread for the chunks or `self._client.aio` if I can.
            # But let's look at `google-genai` docs. `client.aio.models.generate_content_stream` is the standard way.
            # Let's assume we can use `self._client.aio.models.generate_content_stream`. Wait, if the provider init did `genai.Client()`, does it have `.aio`? Yes.
            
            if hasattr(self._client, "aio"):
                response_stream = await self._client.aio.models.generate_content_stream(
                    model=self._model,
                    contents=prompt,
                    config=gen_config,
                )
                async for chunk in response_stream:
                    if chunk.text:
                        yield chunk.text
            else:
                # Fallback to wrapping the sync iterator
                response_stream = await asyncio.to_thread(
                    self._client.models.generate_content_stream,
                    model=self._model,
                    contents=prompt,
                    config=gen_config,
                )
                
                def _get_next(iterator):
                    try:
                        return next(iterator)
                    except StopIteration:
                        return None

                iterator = iter(response_stream)
                while True:
                    chunk = await asyncio.to_thread(_get_next, iterator)
                    if chunk is None:
                        break
                    if chunk.text:
                        yield chunk.text

        except APIError as exc:
            raise _classify_gemini_error(exc) from exc
        except (
            httpx.TimeoutException,
            httpx.ConnectError,
            httpx.RemoteProtocolError,
            httpx.NetworkError,
            TimeoutError,
            ConnectionError,
            BrokenPipeError,
        ) as exc:
            raise _classify_network_error(exc) from exc

