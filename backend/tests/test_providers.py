"""Unit tests for provider implementations — mock the SDK/HTTP calls."""

import pytest

from services.providers.base import (
    ProviderAuthError,
    ProviderConnectionError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)


# ---------------------------------------------------------------------------
# Gemini error classification
# ---------------------------------------------------------------------------


class TestGeminiErrorClassification:
    """Verify _classify_gemini_error maps status codes correctly."""

    def _classify(self, code, status="", message=""):
        """Build a fake APIError and classify it."""
        from services.providers.gemini import _classify_gemini_error

        class _FakeAPIError(Exception):
            pass

        exc = _FakeAPIError(message)
        exc.code = code
        exc.status = status
        return _classify_gemini_error(exc)

    def test_429_is_rate_limit(self):
        result = self._classify(429)
        assert isinstance(result, ProviderRateLimitError)

    def test_resource_exhausted_status_is_rate_limit(self):
        result = self._classify(503, status="RESOURCE_EXHAUSTED")
        assert isinstance(result, ProviderRateLimitError)

    def test_quota_in_message_is_rate_limit(self):
        result = self._classify(400, message="Quota exceeded for this project")
        assert isinstance(result, ProviderRateLimitError)

    def test_401_is_auth(self):
        result = self._classify(401)
        assert isinstance(result, ProviderAuthError)

    def test_403_is_auth(self):
        result = self._classify(403)
        assert isinstance(result, ProviderAuthError)

    def test_400_with_api_key_message_is_auth(self):
        result = self._classify(400, message="Invalid API key provided")
        assert isinstance(result, ProviderAuthError)

    def test_400_generic_is_provider_error(self):
        result = self._classify(400, message="Malformed request")
        assert isinstance(result, ProviderError)
        assert not isinstance(result, ProviderAuthError)

    def test_500_is_provider_error(self):
        result = self._classify(500, message="Internal server error")
        assert isinstance(result, ProviderError)


# ---------------------------------------------------------------------------
# OpenAI error classification
# ---------------------------------------------------------------------------


try:
    import openai as _openai  # noqa: F401
    _has_openai = True
except ImportError:
    _has_openai = False


@pytest.mark.skipif(not _has_openai, reason="openai package not installed")
class TestOpenAIErrorClassification:
    """Verify _classify_openai_error maps OpenAI SDK exceptions correctly."""

    @staticmethod
    def _fake_response(status_code: int):
        """Build a minimal httpx.Response that OpenAI exceptions accept."""
        import httpx

        return httpx.Response(status_code, request=httpx.Request("POST", "https://api.openai.com"))

    def test_rate_limit(self):
        import openai
        from services.providers.openai import _classify_openai_error

        exc = openai.RateLimitError(
            message="Rate limit exceeded",
            response=self._fake_response(429),
            body=None,
        )
        result = _classify_openai_error(exc)
        assert isinstance(result, ProviderRateLimitError)

    def test_auth_error(self):
        import openai
        from services.providers.openai import _classify_openai_error

        exc = openai.AuthenticationError(
            message="Invalid API key",
            response=self._fake_response(401),
            body=None,
        )
        result = _classify_openai_error(exc)
        assert isinstance(result, ProviderAuthError)

    def test_timeout(self):
        import openai
        from services.providers.openai import _classify_openai_error

        exc = openai.APITimeoutError(request=None)
        result = _classify_openai_error(exc)
        assert isinstance(result, ProviderTimeoutError)

    def test_connection_error(self):
        import openai
        from services.providers.openai import _classify_openai_error

        exc = openai.APIConnectionError(request=None)
        result = _classify_openai_error(exc)
        assert isinstance(result, ProviderConnectionError)


# ---------------------------------------------------------------------------
# Anthropic error classification
# ---------------------------------------------------------------------------


class TestAnthropicErrorClassification:
    """Verify _classify_anthropic_error maps SDK exceptions correctly."""

    @staticmethod
    def _make_response(status_code: int):
        import httpx
        return httpx.Response(status_code, request=httpx.Request("POST", "https://api.anthropic.com"))

    def test_rate_limit(self):
        from services.providers.anthropic import _classify_anthropic_error
        import anthropic

        exc = anthropic.RateLimitError(
            "rate limited", response=self._make_response(429), body=None
        )
        result = _classify_anthropic_error(exc)
        assert isinstance(result, ProviderRateLimitError)

    def test_auth_error(self):
        from services.providers.anthropic import _classify_anthropic_error
        import anthropic

        exc = anthropic.AuthenticationError(
            "invalid key", response=self._make_response(401), body=None
        )
        result = _classify_anthropic_error(exc)
        assert isinstance(result, ProviderAuthError)

    def test_permission_error(self):
        from services.providers.anthropic import _classify_anthropic_error
        import anthropic

        exc = anthropic.PermissionDeniedError(
            "permission denied", response=self._make_response(403), body=None
        )
        result = _classify_anthropic_error(exc)
        assert isinstance(result, ProviderAuthError)

    def test_timeout(self):
        from services.providers.anthropic import _classify_anthropic_error
        import anthropic, httpx

        exc = anthropic.APITimeoutError(request=httpx.Request("POST", "https://api.anthropic.com"))
        result = _classify_anthropic_error(exc)
        assert isinstance(result, ProviderTimeoutError)

    def test_connection_error(self):
        from services.providers.anthropic import _classify_anthropic_error
        import anthropic, httpx

        exc = anthropic.APIConnectionError(
            message="connection failed",
            request=httpx.Request("POST", "https://api.anthropic.com"),
        )
        result = _classify_anthropic_error(exc)
        assert isinstance(result, ProviderConnectionError)

    def test_generic_api_error(self):
        from services.providers.anthropic import _classify_anthropic_error
        import anthropic

        exc = anthropic.InternalServerError(
            "internal error", response=self._make_response(500), body=None
        )
        result = _classify_anthropic_error(exc)
        assert isinstance(result, ProviderError)
        assert not isinstance(result, ProviderAuthError)
        assert not isinstance(result, ProviderRateLimitError)


# ---------------------------------------------------------------------------
# Anthropic generate() / generate_stream() response parsing
# ---------------------------------------------------------------------------


class TestAnthropicGenerateParsing:
    """Verify AnthropicLLMProvider.generate() extracts content[0].text."""

    async def test_returns_text_content(self):
        from unittest.mock import AsyncMock, MagicMock
        from services.providers.anthropic import AnthropicLLMProvider

        provider = AnthropicLLMProvider(api_key="test-key")

        fake_text_block = MagicMock()
        fake_text_block.type = "text"
        fake_text_block.text = "Hello from Claude"

        fake_response = MagicMock()
        fake_response.content = [fake_text_block]
        provider._client.messages.create = AsyncMock(return_value=fake_response)

        result = await provider.generate(
            "hi",
            system_instruction="be helpful",
            temperature=0.2,
            max_output_tokens=64,
        )

        assert result == "Hello from Claude"

    async def test_skips_non_text_blocks_and_falls_back(self):
        from unittest.mock import AsyncMock, MagicMock
        from services.providers.anthropic import AnthropicLLMProvider

        provider = AnthropicLLMProvider(api_key="test-key")

        tool_use_block = MagicMock()
        tool_use_block.type = "tool_use"
        tool_use_block.name = "get_weather"

        fake_response = MagicMock()
        fake_response.content = [tool_use_block]
        provider._client.messages.create = AsyncMock(return_value=fake_response)

        result = await provider.generate(
            "hi",
            system_instruction="be helpful",
            temperature=0.2,
            max_output_tokens=64,
        )

        assert result == "No response."

    async def test_streaming_yields_text(self):
        from unittest.mock import AsyncMock, MagicMock
        from services.providers.anthropic import AnthropicLLMProvider

        provider = AnthropicLLMProvider(api_key="test-key")

        fake_stream = MagicMock()
        fake_text_stream = AsyncMock()
        fake_text_stream.__aiter__.return_value = iter(["Hello", " ", "from", " ", "Claude"])
        type(fake_stream).text_stream = fake_text_stream

        fake_stream_manager = MagicMock()
        fake_stream_manager.__aenter__.return_value = fake_stream
        fake_stream_manager.__aexit__.return_value = None

        provider._client.messages.stream = MagicMock(return_value=fake_stream_manager)

        tokens = []
        async for token in provider.generate_stream(
            "hi",
            system_instruction="be helpful",
            temperature=0.2,
            max_output_tokens=64,
        ):
            tokens.append(token)

        assert "".join(tokens) == "Hello from Claude"

    async def test_missing_api_key_raises_auth_error(self):
        from unittest.mock import AsyncMock
        from services.providers.anthropic import AnthropicLLMProvider
        from services.providers.base import ProviderAuthError
        import anthropic, httpx

        provider = AnthropicLLMProvider(api_key=None)

        req = httpx.Request("POST", "https://api.anthropic.com")
        provider._client.messages.create = AsyncMock(
            side_effect=anthropic.AuthenticationError(
                "invalid API key", response=httpx.Response(401, request=req), body=None
            )
        )

        with pytest.raises(ProviderAuthError):
            await provider.generate(
                "hi",
                system_instruction="be helpful",
                temperature=0.2,
                max_output_tokens=64,
            )


# ---------------------------------------------------------------------------
# Ollama error classification
# ---------------------------------------------------------------------------


class TestOllamaErrorClassification:
    """Verify Ollama error mappers classify httpx errors correctly."""

    def test_http_429_is_rate_limit(self):
        import httpx
        from services.providers.ollama import _classify_http_error

        response = httpx.Response(429, request=httpx.Request("POST", "http://test"))
        exc = httpx.HTTPStatusError("rate limited", request=response.request, response=response)
        result = _classify_http_error(exc)
        assert isinstance(result, ProviderRateLimitError)

    def test_http_401_is_auth(self):
        import httpx
        from services.providers.ollama import _classify_http_error

        response = httpx.Response(401, request=httpx.Request("POST", "http://test"))
        exc = httpx.HTTPStatusError("unauthorized", request=response.request, response=response)
        result = _classify_http_error(exc)
        assert isinstance(result, ProviderAuthError)

    def test_http_500_is_provider_error(self):
        import httpx
        from services.providers.ollama import _classify_http_error

        response = httpx.Response(500, request=httpx.Request("POST", "http://test"))
        exc = httpx.HTTPStatusError("server error", request=response.request, response=response)
        result = _classify_http_error(exc)
        assert isinstance(result, ProviderError)

    def test_timeout_is_provider_timeout(self):
        import httpx
        from services.providers.ollama import _classify_network_error

        exc = httpx.ReadTimeout("timed out")
        result = _classify_network_error(exc)
        assert isinstance(result, ProviderTimeoutError)

    def test_connect_error_is_connection(self):
        import httpx
        from services.providers.ollama import _classify_network_error

        exc = httpx.ConnectError("refused")
        result = _classify_network_error(exc)
        assert isinstance(result, ProviderConnectionError)


# ---------------------------------------------------------------------------
# Gemini embed() response parsing and batching
# ---------------------------------------------------------------------------


class TestGeminiEmbedParsing:
    """Verify GeminiEmbeddingProvider.embed() batches correctly and extracts
    ``.values`` from each item in ``result.embeddings``."""

    async def test_single_batch_happy_path(self):
        from unittest.mock import MagicMock

        from services.providers.gemini import GeminiEmbeddingProvider

        provider = GeminiEmbeddingProvider(api_key="test-key")

        def fake_embed_content(*, model, contents):
            result = MagicMock()
            result.embeddings = [MagicMock(values=[0.1, 0.2, 0.3]) for _ in contents]
            return result

        provider._client.models.embed_content = fake_embed_content

        result = await provider.embed(["hello", "world"])

        assert result == [[0.1, 0.2, 0.3], [0.1, 0.2, 0.3]]

    async def test_large_input_is_split_into_batches_of_100(self):
        """150 texts → 2 calls (100, 50), results concatenated in order."""
        from unittest.mock import MagicMock

        from services.providers.gemini import GeminiEmbeddingProvider

        provider = GeminiEmbeddingProvider(api_key="test-key")

        call_batch_sizes: list[int] = []

        def fake_embed_content(*, model, contents):
            call_batch_sizes.append(len(contents))
            result = MagicMock()
            # Tag each embedding with its batch size so we can assert order.
            result.embeddings = [
                MagicMock(values=[float(len(contents))]) for _ in contents
            ]
            return result

        provider._client.models.embed_content = fake_embed_content

        texts = [f"t{i}" for i in range(150)]
        result = await provider.embed(texts)

        assert call_batch_sizes == [100, 50]
        assert len(result) == 150
        assert result[0] == [100.0]    # first 100 came from the 100-sized batch
        assert result[99] == [100.0]
        assert result[100] == [50.0]   # last 50 came from the 50-sized batch
        assert result[149] == [50.0]


# ---------------------------------------------------------------------------
# OpenAI generate() response parsing
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _has_openai, reason="openai package not installed")
class TestOpenAIGenerateParsing:
    """Verify OpenAILLMProvider.generate() extracts choices[0].message.content."""

    async def test_returns_message_content(self):
        from unittest.mock import AsyncMock, MagicMock

        from services.providers.openai import OpenAILLMProvider

        provider = OpenAILLMProvider(api_key="test-key")

        fake_response = MagicMock()
        fake_response.choices = [MagicMock()]
        fake_response.choices[0].message.content = "Hello from OpenAI"
        provider._client.chat.completions.create = AsyncMock(return_value=fake_response)

        result = await provider.generate(
            "hi",
            system_instruction="be helpful",
            temperature=0.2,
            max_output_tokens=64,
        )

        assert result == "Hello from OpenAI"

    async def test_none_content_falls_back_to_placeholder(self):
        """Exercise the ``or "No response."`` fallback when the SDK returns None."""
        from unittest.mock import AsyncMock, MagicMock

        from services.providers.openai import OpenAILLMProvider

        provider = OpenAILLMProvider(api_key="test-key")

        fake_response = MagicMock()
        fake_response.choices = [MagicMock()]
        fake_response.choices[0].message.content = None
        provider._client.chat.completions.create = AsyncMock(return_value=fake_response)

        result = await provider.generate(
            "hi",
            system_instruction="be helpful",
            temperature=0.2,
            max_output_tokens=64,
        )

        assert result == "No response."


# ---------------------------------------------------------------------------
# Ollama embed() / generate() response parsing
# ---------------------------------------------------------------------------


class TestOllamaEmbedParsing:
    """Verify OllamaEmbeddingProvider.embed() extracts response['embeddings']."""

    async def test_returns_embeddings_list(self):
        from unittest.mock import AsyncMock, MagicMock

        from services.providers.ollama import OllamaEmbeddingProvider

        provider = OllamaEmbeddingProvider()

        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json = MagicMock(
            return_value={"embeddings": [[0.1, 0.2], [0.3, 0.4]]}
        )
        provider._client.post = AsyncMock(return_value=fake_response)

        result = await provider.embed(["a", "b"])

        assert result == [[0.1, 0.2], [0.3, 0.4]]

    async def test_fallback_to_singular_embedding_key(self):
        """Older Ollama versions (pre-0.1.34) use 'embedding' (singular)."""
        from unittest.mock import AsyncMock, MagicMock
        from services.providers.ollama import OllamaEmbeddingProvider

        provider = OllamaEmbeddingProvider()

        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json = MagicMock(
            return_value={"embedding": [0.1, 0.2, 0.3]}
        )
        provider._client.post = AsyncMock(return_value=fake_response)

        result = await provider.embed(["test"])

        assert result == [[0.1, 0.2, 0.3]]

    async def test_missing_both_keys_raises_provider_error(self):
        from unittest.mock import AsyncMock, MagicMock
        from services.providers.ollama import OllamaEmbeddingProvider, ProviderError

        provider = OllamaEmbeddingProvider()

        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        # Response with neither 'embeddings' nor 'embedding'
        fake_response.json = MagicMock(return_value={"something_else": "here"})
        provider._client.post = AsyncMock(return_value=fake_response)

        with pytest.raises(ProviderError) as exc:
            await provider.embed(["a", "b"])

        assert "Unexpected Ollama embed response shape" in str(exc.value)
        assert "something_else" in str(exc.value)


class TestOllamaGenerateParsing:
    """Verify OllamaLLMProvider.generate() parses response['response'] with fallback."""

    async def test_returns_response_field(self):
        from unittest.mock import AsyncMock, MagicMock

        from services.providers.ollama import OllamaLLMProvider

        provider = OllamaLLMProvider()

        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json = MagicMock(return_value={"response": "Hi there."})
        provider._client.post = AsyncMock(return_value=fake_response)

        result = await provider.generate(
            "hi",
            system_instruction="be helpful",
            temperature=0.2,
            max_output_tokens=64,
        )

        assert result == "Hi there."

    async def test_missing_response_key_falls_back_to_placeholder(self):
        """Exercise ``.get("response", "No response.")`` when the key is absent."""
        from unittest.mock import AsyncMock, MagicMock

        from services.providers.ollama import OllamaLLMProvider

        provider = OllamaLLMProvider()

        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json = MagicMock(return_value={})
        provider._client.post = AsyncMock(return_value=fake_response)

        result = await provider.generate(
            "hi",
            system_instruction="be helpful",
            temperature=0.2,
            max_output_tokens=64,
        )

        assert result == "No response."


# ---------------------------------------------------------------------------
# Voyage AI embed() response parsing
# ---------------------------------------------------------------------------


class TestVoyageEmbedParsing:
    """Verify VoyageEmbeddingProvider.embed() extracts data[i]["embedding"]."""

    async def test_returns_embeddings_list(self):
        from unittest.mock import AsyncMock, MagicMock
        from services.providers.voyage import VoyageEmbeddingProvider

        provider = VoyageEmbeddingProvider(api_key="test-key")

        fake_response = MagicMock()
        fake_response.raise_for_status = MagicMock()
        fake_response.json = MagicMock(
            return_value={
                "object": "list",
                "data": [
                    {"object": "embedding", "embedding": [0.1, 0.2], "index": 0},
                    {"object": "embedding", "embedding": [0.3, 0.4], "index": 1},
                ],
            }
        )
        provider._client.post = AsyncMock(return_value=fake_response)

        result = await provider.embed(["a", "b"])

        assert result == [[0.1, 0.2], [0.3, 0.4]]

    async def test_missing_api_key_raises_auth_error(self, monkeypatch):
        from services.providers.voyage import VoyageEmbeddingProvider, config
        from services.providers.base import ProviderAuthError

        monkeypatch.setattr(config, "VOYAGE_API_KEY", None)
        provider = VoyageEmbeddingProvider(api_key=None)

        with pytest.raises(ProviderAuthError, match="VOYAGE_API_KEY is not configured"):
            await provider.embed(["test"])

    async def test_batches_large_inputs(self):
        from unittest.mock import AsyncMock, MagicMock
        from services.providers.voyage import VoyageEmbeddingProvider

        provider = VoyageEmbeddingProvider(api_key="test-key")
        BATCH = 128
        total = BATCH * 2 + 1

        call_count = 0

        async def fake_post(url, **kwargs):
            nonlocal call_count
            call_count += 1
            batch = kwargs.get("json", {}).get("input", [])
            batch_size = len(batch)
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            dim = 3
            embeddings = [
                {"object": "embedding", "embedding": [float(call_count)] * dim, "index": j}
                for j in range(batch_size)
            ]
            resp.json = MagicMock(return_value={"object": "list", "data": embeddings})
            return resp

        provider._client.post = fake_post

        texts = ["t"] * total
        result = await provider.embed(texts)

        assert call_count == 3
        assert len(result) == total
        assert result[0] == [1.0, 1.0, 1.0]
        assert result[BATCH - 1] == [1.0, 1.0, 1.0]
        assert result[BATCH] == [2.0, 2.0, 2.0]
        assert result[-1] == [3.0, 3.0, 3.0]


# ---------------------------------------------------------------------------
# Voyage AI error classification
# ---------------------------------------------------------------------------


class TestVoyageErrorClassification:
    """Verify Voyage error mappers classify httpx errors correctly."""

    def test_http_429_is_rate_limit(self):
        import httpx
        from services.providers.voyage import _classify_http_error, _classify_network_error

        response = httpx.Response(429, request=httpx.Request("POST", "http://test"))
        exc = httpx.HTTPStatusError("rate limited", request=response.request, response=response)
        result = _classify_http_error(exc)
        assert isinstance(result, ProviderRateLimitError)

    def test_http_401_is_auth(self):
        import httpx
        from services.providers.voyage import _classify_http_error

        response = httpx.Response(401, request=httpx.Request("POST", "http://test"))
        exc = httpx.HTTPStatusError("unauthorized", request=response.request, response=response)
        result = _classify_http_error(exc)
        assert isinstance(result, ProviderAuthError)

    def test_http_500_is_provider_error(self):
        import httpx
        from services.providers.voyage import _classify_http_error

        response = httpx.Response(500, request=httpx.Request("POST", "http://test"))
        exc = httpx.HTTPStatusError("server error", request=response.request, response=response)
        result = _classify_http_error(exc)
        assert isinstance(result, ProviderError)

    def test_timeout_is_provider_timeout(self):
        import httpx
        from services.providers.voyage import _classify_network_error

        exc = httpx.ReadTimeout("timed out")
        result = _classify_network_error(exc)
        assert isinstance(result, ProviderTimeoutError)

    def test_connect_error_is_connection(self):
        import httpx
        from services.providers.voyage import _classify_network_error

        exc = httpx.ConnectError("refused")
        result = _classify_network_error(exc)
        assert isinstance(result, ProviderConnectionError)


class TestEmbeddingDimResolution:
    """embedding_dim must not silently default for unknown models."""

    def test_unknown_model_raises(self):
        from services.providers.gemini import GeminiEmbeddingProvider

        provider = GeminiEmbeddingProvider(
            api_key="test-key", model="totally-unknown-model-xyz"
        )
        with pytest.raises(ValueError, match="Unknown embedding model"):
            _ = provider.embedding_dim

    def test_provider_prefixed_name_resolves(self):
        """Slash-suffix lookup must work without importing optional OpenAI deps."""
        from services.providers.ollama import OllamaEmbeddingProvider

        provider = OllamaEmbeddingProvider(model="registry/nomic-embed-text")
        assert provider.embedding_dim == 768
