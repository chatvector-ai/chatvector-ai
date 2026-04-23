"""Tests for provider factory functions — correct selection, caching, errors."""

import os

import pytest

import services.providers as providers_mod
from services.providers.base import EmbeddingProvider, LLMProvider

try:
    import openai as _openai  # noqa: F401
    _has_openai = True
except ImportError:
    _has_openai = False

_skip_openai = pytest.mark.skipif(not _has_openai, reason="openai package not installed")

# Skip OpenAI tests if API key is not configured
skip_if_no_openai = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set — skipping OpenAI provider tests",
)


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset provider singletons before and after each test."""
    providers_mod._embedding_provider = None
    providers_mod._llm_provider = None
    yield
    providers_mod._embedding_provider = None
    providers_mod._llm_provider = None


# ---------------------------------------------------------------------------
# Embedding provider factory
# ---------------------------------------------------------------------------


class TestGetEmbeddingProvider:
    def test_default_returns_gemini(self, monkeypatch):
        monkeypatch.setattr(providers_mod.config, "EMBEDDING_PROVIDER", "gemini")
        provider = providers_mod.get_embedding_provider()
        assert isinstance(provider, EmbeddingProvider)
        assert type(provider).__name__ == "GeminiEmbeddingProvider"

    @_skip_openai
    @skip_if_no_openai
    def test_openai_selection(self, monkeypatch):
        monkeypatch.setattr(providers_mod.config, "EMBEDDING_PROVIDER", "openai")
        provider = providers_mod.get_embedding_provider()
        assert isinstance(provider, EmbeddingProvider)
        assert type(provider).__name__ == "OpenAIEmbeddingProvider"

    def test_ollama_selection(self, monkeypatch):
        monkeypatch.setattr(providers_mod.config, "EMBEDDING_PROVIDER", "ollama")
        provider = providers_mod.get_embedding_provider()
        assert isinstance(provider, EmbeddingProvider)
        assert type(provider).__name__ == "OllamaEmbeddingProvider"

    def test_singleton_caching(self, monkeypatch):
        monkeypatch.setattr(providers_mod.config, "EMBEDDING_PROVIDER", "ollama")
        p1 = providers_mod.get_embedding_provider()
        p2 = providers_mod.get_embedding_provider()
        assert p1 is p2

    def test_unknown_provider_raises(self, monkeypatch):
        monkeypatch.setattr(providers_mod.config, "EMBEDDING_PROVIDER", "unknown")
        with pytest.raises(ValueError, match="Unknown EMBEDDING_PROVIDER"):
            providers_mod.get_embedding_provider()


# ---------------------------------------------------------------------------
# LLM provider factory
# ---------------------------------------------------------------------------


class TestGetLLMProvider:
    def test_default_returns_gemini(self, monkeypatch):
        monkeypatch.setattr(providers_mod.config, "LLM_PROVIDER", "gemini")
        provider = providers_mod.get_llm_provider()
        assert isinstance(provider, LLMProvider)
        assert type(provider).__name__ == "GeminiLLMProvider"

    @_skip_openai
    @skip_if_no_openai
    def test_openai_selection(self, monkeypatch):
        monkeypatch.setattr(providers_mod.config, "LLM_PROVIDER", "openai")
        provider = providers_mod.get_llm_provider()
        assert isinstance(provider, LLMProvider)
        assert type(provider).__name__ == "OpenAILLMProvider"

    def test_ollama_selection(self, monkeypatch):
        monkeypatch.setattr(providers_mod.config, "LLM_PROVIDER", "ollama")
        provider = providers_mod.get_llm_provider()
        assert isinstance(provider, LLMProvider)
        assert type(provider).__name__ == "OllamaLLMProvider"

    def test_singleton_caching(self, monkeypatch):
        monkeypatch.setattr(providers_mod.config, "LLM_PROVIDER", "ollama")
        p1 = providers_mod.get_llm_provider()
        p2 = providers_mod.get_llm_provider()
        assert p1 is p2

    def test_unknown_provider_raises(self, monkeypatch):
        monkeypatch.setattr(providers_mod.config, "LLM_PROVIDER", "unknown")
        with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
            providers_mod.get_llm_provider()
