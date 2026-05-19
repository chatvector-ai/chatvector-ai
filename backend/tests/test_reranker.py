"""Tests for retrieval reranking layer."""

from unittest.mock import patch

import pytest

from core.config import config
from db.base import ChunkMatch
from services.reranker import _reset_reranker_provider, get_reranker_provider, rerank_chunks_if_enabled
from services.reranker.base import RerankRequest
from services.reranker.noop import NoopRerankerProvider
from services.reranker.similarity import SimilarityRerankerProvider


def _chunk(chunk_id: str, text: str, *, similarity: float | None = None) -> ChunkMatch:
    return ChunkMatch(
        id=chunk_id,
        chunk_text=text,
        document_id="doc-1",
        chunk_index=0,
        similarity=similarity,
    )


@pytest.fixture(autouse=True)
def reset_reranker_singleton():
    _reset_reranker_provider()
    yield
    _reset_reranker_provider()


@pytest.mark.asyncio
async def test_rerank_disabled_returns_original_order():
    chunks = [
        _chunk("a", "alpha content", similarity=0.1),
        _chunk("b", "beta content", similarity=0.9),
    ]
    with patch.object(config, "ENABLE_RERANKING", False):
        result = await rerank_chunks_if_enabled("beta query", chunks, top_k=2)

    assert [c.id for c in result] == ["a", "b"]


@pytest.mark.asyncio
async def test_rerank_disabled_does_not_truncate_to_top_k():
    chunks = [_chunk(f"c{i}", f"content {i}", similarity=0.1) for i in range(6)]
    with patch.object(config, "ENABLE_RERANKING", False):
        result = await rerank_chunks_if_enabled("query", chunks, top_k=3)

    assert len(result) == 6
    assert [c.id for c in result] == [f"c{i}" for i in range(6)]


@pytest.mark.asyncio
async def test_similarity_reranker_promotes_lexical_match():
    chunks = [
        _chunk("low", "unrelated text about cats", similarity=0.5),
        _chunk("high", "beta query terms appear here", similarity=0.5),
    ]
    provider = SimilarityRerankerProvider()
    result = await provider.rerank(
        RerankRequest(query="beta query", candidates=chunks, top_k=2)
    )

    assert result.reranked_order[0] == "high"
    assert result.original_order == ["low", "high"]
    assert result.candidates[0].similarity is not None


@pytest.mark.asyncio
async def test_rerank_enabled_uses_provider_and_logs_order_change():
    chunks = [
        _chunk("low", "unrelated text about cats", similarity=0.5),
        _chunk("high", "beta query terms appear here", similarity=0.5),
    ]
    with patch.object(config, "ENABLE_RERANKING", True), patch.object(
        config, "RERANKER_PROVIDER", "similarity"
    ):
        _reset_reranker_provider()
        result = await rerank_chunks_if_enabled("beta query", chunks, top_k=2)

    assert [c.id for c in result] == ["high", "low"]
    assert isinstance(get_reranker_provider(), SimilarityRerankerProvider)


@pytest.mark.asyncio
async def test_rerank_result_format_is_stable():
    chunks = [_chunk("only", "single chunk", similarity=0.5)]
    provider = SimilarityRerankerProvider()
    result = await provider.rerank(RerankRequest(query="q", candidates=chunks))

    assert result.original_order == ["only"]
    assert result.reranked_order == ["only"]
    assert len(result.candidates) == 1
    assert result.candidates[0].chunk_text == "single chunk"


def test_unknown_reranker_provider_raises():
    with patch.object(config, "ENABLE_RERANKING", True), patch.object(
        config, "RERANKER_PROVIDER", "unknown"
    ):
        _reset_reranker_provider()
        with pytest.raises(ValueError, match="Unknown RERANKER_PROVIDER"):
            get_reranker_provider()
