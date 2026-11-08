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
    page_number: int | None = 1,
    page_end: int | None = None,
    vector_score: float | None = None,
    full_text_score: float | None = None,
    rrf_score: float | None = None,
    reranker_score: float | None = None,
    rerank_order: int | None = None,
) -> ChunkMatch:
    return ChunkMatch(
        id=chunk_id,
        chunk_text=f"chunk {chunk_id}",
        file_name="doc.pdf",
        page_number=page_number,
        page_end=page_end,
        chunk_index=0,
        similarity=similarity,
        score_type=score_type,
        vector_score=vector_score,
        full_text_score=full_text_score,
        rrf_score=rrf_score,
        reranker_score=reranker_score,
        rerank_order=rerank_order,
    )


def test_build_sources_includes_score_type():
    sources = _build_sources(
        [
            _chunk("c1", similarity=0.91, score_type=SCORE_TYPE_VECTOR, vector_score=0.91),
            _chunk(
                "c2",
                similarity=0.03,
                score_type=SCORE_TYPE_HYBRID_RRF,
                vector_score=0.88,
                full_text_score=0.42,
                rrf_score=0.03,
            ),
        ]
    )

    assert sources == [
        {
            "file_name": "doc.pdf",
            "page_number": 1,
            "chunk_index": 0,
            "score": 0.91,
            "score_type": SCORE_TYPE_VECTOR,
            "vector_score": 0.91,
        },
        {
            "file_name": "doc.pdf",
            "page_number": 1,
            "chunk_index": 0,
            "score": 0.03,
            "score_type": SCORE_TYPE_HYBRID_RRF,
            "vector_score": 0.88,
            "full_text_score": 0.42,
            "rrf_score": 0.03,
        },
    ]


def test_build_sources_omits_absent_component_fields():
    sources = _build_sources([_chunk("c1", similarity=0.5)])

    assert "page_end" not in sources[0]
    assert "vector_score" not in sources[0]
    assert "full_text_score" not in sources[0]
    assert "rrf_score" not in sources[0]
    assert "reranker_score" not in sources[0]
    assert "rerank_order" not in sources[0]


def test_build_sources_includes_reranker_component_fields():
    sources = _build_sources(
        [
            _chunk(
                "c1",
                similarity=0.77,
                score_type=SCORE_TYPE_RERANKED,
                vector_score=0.55,
                rrf_score=0.02,
                reranker_score=0.77,
                rerank_order=1,
            )
        ]
    )

    assert sources[0]["score"] == 0.77
    assert sources[0]["score_type"] == SCORE_TYPE_RERANKED
    assert sources[0]["vector_score"] == 0.55
    assert sources[0]["rrf_score"] == 0.02
    assert sources[0]["reranker_score"] == 0.77
    assert sources[0]["rerank_order"] == 1


def test_build_sources_includes_page_end_for_multi_page_chunk():
    sources = _build_sources(
        [_chunk("c1", page_number=1, page_end=2, similarity=0.5)]
    )

    assert sources[0]["page_number"] == 1
    assert sources[0]["page_end"] == 2


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
    assert merged[0].rrf_score == scores["b"]
    assert merged[0].vector_score is None


def test_merge_chunk_matches_with_scores_preserves_component_scores():
    matches_by_id = {
        "a": _chunk("a", vector_score=0.9, full_text_score=0.4),
        "b": _chunk("b", vector_score=0.7),
    }
    scores = reciprocal_rank_fusion_scores([["a", "b"], ["b"]], limit=2)

    merged = merge_chunk_matches_with_scores(
        ["b", "a"],
        matches_by_id,
        scores,
        score_type=SCORE_TYPE_HYBRID_RRF,
    )

    assert merged[0].vector_score == 0.7
    assert merged[0].full_text_score is None
    assert merged[0].rrf_score == scores["b"]
    assert merged[1].vector_score == 0.9
    assert merged[1].full_text_score == 0.4
    assert merged[1].rrf_score == scores["a"]


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
    assert result.candidates[0].reranker_score is not None
    assert result.candidates[0].rerank_order == 1
    assert result.candidates[1].rerank_order == 2


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
        vector_score=0.88,
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
    assert results[0].vector_score == 0.88


@pytest.mark.asyncio
async def test_find_similar_chunks_hybrid_path_populates_component_scores():
    pytest.importorskip("pgvector")
    from db.sqlalchemy_service import SQLAlchemyService

    service = SQLAlchemyService()
    service._retrieval_semaphore = __import__("asyncio").Semaphore(10)

    shared_vector = _chunk("shared", similarity=0.91, vector_score=0.91)
    shared_keyword = _chunk("shared", similarity=0.33, full_text_score=0.33)
    vec_only = _chunk("vec-only", similarity=0.75, vector_score=0.75)
    key_only = _chunk("key-only", similarity=0.33, full_text_score=0.33)

    service._find_vector_chunks = AsyncMock(return_value=[shared_vector, vec_only])
    service._find_keyword_chunks = AsyncMock(return_value=[shared_keyword, key_only])

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

    by_id = {match.id: match for match in results}
    assert by_id["shared"].vector_score == 0.91
    assert by_id["shared"].full_text_score == 0.33
    assert by_id["shared"].rrf_score is not None
    assert by_id["vec-only"].vector_score == 0.75
    assert by_id["vec-only"].full_text_score is None
    assert by_id["key-only"].vector_score is None
    assert by_id["key-only"].full_text_score == 0.33


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


def test_chat_source_response_model_documents_component_fields():
    from routes.chat import ChatSourceResponse

    schema = ChatSourceResponse.model_json_schema()
    props = schema["properties"]
    for field in (
        "vector_score",
        "full_text_score",
        "rrf_score",
        "reranker_score",
        "rerank_order",
    ):
        assert field in props
