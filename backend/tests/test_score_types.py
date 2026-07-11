"""Tests for citation score_type metadata across retrieval modes."""

from unittest.mock import AsyncMock, patch

import pytest

from core.config import config
from db.base import ChunkMatch
from services.chat_service import _build_sources
from services.retrieval_service import (
    SCORE_TYPE_HYBRID_RRF,
    SCORE_TYPE_RERANKED,
    SCORE_TYPE_VECTOR,
    merge_chunk_matches_with_scores,
    reciprocal_rank_fusion_scores,
)
from services.reranker.base import RerankRequest
from services.reranker.similarity import SimilarityRerankerProvider


def _chunk(
    chunk_id: str,
    *,
    similarity: float | None = 0.5,
    score_type: str | None = SCORE_TYPE_VECTOR,
) -> ChunkMatch:
    return ChunkMatch(
        id=chunk_id,
        chunk_text=f"chunk {chunk_id}",
        file_name="doc.pdf",
        page_number=1,
        chunk_index=0,
        similarity=similarity,
        score_type=score_type,
    )


def test_build_sources_includes_score_type():
    sources = _build_sources(
        [
            _chunk("c1", similarity=0.91, score_type=SCORE_TYPE_VECTOR),
            _chunk("c2", similarity=0.03, score_type=SCORE_TYPE_HYBRID_RRF),
        ]
    )

    assert sources == [
        {
            "file_name": "doc.pdf",
            "page_number": 1,
            "chunk_index": 0,
            "score": 0.91,
            "score_type": SCORE_TYPE_VECTOR,
        },
        {
            "file_name": "doc.pdf",
            "page_number": 1,
            "chunk_index": 0,
            "score": 0.03,
            "score_type": SCORE_TYPE_HYBRID_RRF,
        },
    ]


def test_reciprocal_rank_fusion_scores_returns_rrf_values():
    scores = reciprocal_rank_fusion_scores(
        [["a", "b"], ["b", "c"]],
        limit=2,
    )

    assert set(scores) == {"b", "a"}
    assert scores["b"] > scores["a"]


def test_merge_chunk_matches_with_scores_sets_hybrid_rrf_type():
    matches_by_id = {
        "a": _chunk("a"),
        "b": _chunk("b"),
    }
    scores = reciprocal_rank_fusion_scores([["a", "b"], ["b"]], limit=2)

    merged = merge_chunk_matches_with_scores(
        ["b", "a"],
        matches_by_id,
        scores,
        score_type=SCORE_TYPE_HYBRID_RRF,
    )

    assert [match.id for match in merged] == ["b", "a"]
    assert all(match.score_type == SCORE_TYPE_HYBRID_RRF for match in merged)
    assert merged[0].similarity == scores["b"]


@pytest.mark.asyncio
async def test_similarity_reranker_sets_reranked_score_type():
    provider = SimilarityRerankerProvider()
    chunks = [
        _chunk("low", similarity=0.2, score_type=SCORE_TYPE_VECTOR),
        _chunk("high", similarity=0.2, score_type=SCORE_TYPE_HYBRID_RRF),
    ]

    result = await provider.rerank(
        RerankRequest(query="high beta", candidates=chunks, top_k=2)
    )

    assert result.candidates[0].score_type == SCORE_TYPE_RERANKED
    assert result.candidates[0].similarity is not None


@pytest.mark.asyncio
async def test_rerank_disabled_preserves_vector_score_type():
    from services.reranker import rerank_chunks_if_enabled

    chunks = [_chunk("only", score_type=SCORE_TYPE_VECTOR)]

    with patch.object(config, "ENABLE_RERANKING", False):
        result = await rerank_chunks_if_enabled("question", chunks, top_k=1)

    assert result[0].score_type == SCORE_TYPE_VECTOR


@pytest.mark.asyncio
async def test_find_similar_chunks_vector_path_sets_score_type():
    pytest.importorskip("pgvector")
    from db.sqlalchemy_service import SQLAlchemyService

    service = SQLAlchemyService()
    service._retrieval_semaphore = __import__("asyncio").Semaphore(10)
    vector_match = ChunkMatch(
        id="vec-1",
        chunk_text="vector chunk",
        similarity=0.88,
        score_type=SCORE_TYPE_VECTOR,
    )
    service._find_vector_chunks = AsyncMock(return_value=[vector_match])

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    service.async_session = lambda: _FakeSession()

    with patch.object(config, "HYBRID_RETRIEVAL_ENABLED", False):
        results = await service.find_similar_chunks(
            "doc-1",
            [0.1, 0.2],
            5,
            tenant_id="dev",
            query_text="lookup",
        )

    assert results[0].score_type == SCORE_TYPE_VECTOR


@pytest.mark.asyncio
async def test_find_similar_chunks_hybrid_path_sets_hybrid_rrf_score_type():
    pytest.importorskip("pgvector")
    from db.sqlalchemy_service import SQLAlchemyService

    service = SQLAlchemyService()
    service._retrieval_semaphore = __import__("asyncio").Semaphore(10)
    service._find_vector_chunks = AsyncMock(
        return_value=[_chunk("shared"), _chunk("vec-only")]
    )
    service._find_keyword_chunks = AsyncMock(
        return_value=[_chunk("shared"), _chunk("key-only")]
    )

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    service.async_session = lambda: _FakeSession()

    with patch.object(config, "HYBRID_RETRIEVAL_ENABLED", True):
        results = await service.find_similar_chunks(
            "doc-1",
            [0.1, 0.2],
            3,
            tenant_id="dev",
            query_text="lookup",
        )

    assert all(match.score_type == SCORE_TYPE_HYBRID_RRF for match in results)
    assert all(match.similarity is not None for match in results)
