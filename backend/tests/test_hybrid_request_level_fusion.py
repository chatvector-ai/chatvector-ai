"""Request-scoped hybrid RRF fusion (multi-document orchestration)."""

from unittest.mock import AsyncMock, patch

import pytest

from core.config import config
from db.base import SCORE_TYPE_HYBRID_RRF, SCORE_TYPE_VECTOR, ChunkMatch
from services.chat_service import retrieve_for_documents
from services.retrieval_config import RetrievalProcessDefaults, resolve_retrieval_config
from services.retrieval_service import (
    RRF_K_DEFAULT,
    fuse_request_level_hybrid_rrf,
    reciprocal_rank_fusion_scores,
)


def _chunk(
    document_id: str,
    chunk_index: int,
    *,
    chunk_id: str | None = None,
    vector_score: float | None = None,
    full_text_score: float | None = None,
    similarity: float | None = None,
    score_type: str = SCORE_TYPE_VECTOR,
) -> ChunkMatch:
    cid = chunk_id or f"{document_id}:{chunk_index}"
    return ChunkMatch(
        id=cid,
        chunk_text=f"{document_id}#{chunk_index}",
        document_id=document_id,
        chunk_index=chunk_index,
        similarity=similarity if similarity is not None else vector_score,
        score_type=score_type,
        vector_score=vector_score,
        full_text_score=full_text_score,
        rrf_score=similarity if score_type == SCORE_TYPE_HYBRID_RRF else None,
        file_name=f"{document_id}.txt",
    )


def _effective(**fields):
    return resolve_retrieval_config(fields, RetrievalProcessDefaults.from_process())


@pytest.fixture
def retrieval_env(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_RERANKING", False)
    monkeypatch.setattr(config, "HYBRID_RETRIEVAL_ENABLED", False)
    monkeypatch.setattr(config, "QUERY_TRANSFORMATION_ENABLED", False)
    monkeypatch.setattr(config, "ENABLE_GRAPH_RETRIEVAL", False)


def _lists_by_doc(mapping: dict[str, tuple[list[ChunkMatch], list[ChunkMatch]]]):
    async def fake_hybrid_lists(**kwargs):
        return mapping[kwargs["doc_id"]]

    return AsyncMock(side_effect=fake_hybrid_lists)


def _find_by_doc(chunks_by_doc: dict[str, list[ChunkMatch]]):
    async def fake_find(**kwargs):
        return list(chunks_by_doc[kwargs["doc_id"]])

    return AsyncMock(side_effect=fake_find)


async def _retrieve_hybrid(document_ids, lists_by_doc, *, match_count=10, **kwargs):
    with (
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])),
        patch(
            "services.chat_service.find_hybrid_ranked_lists",
            new=_lists_by_doc(lists_by_doc),
        ),
        patch(
            "services.chat_service.find_similar_chunks",
            new=AsyncMock(side_effect=AssertionError("unexpected find_similar_chunks")),
        ),
    ):
        return await retrieve_for_documents(
            "hybrid query",
            document_ids,
            "dev",
            _effective(
                reranking_enabled=False,
                hybrid_enabled=True,
                match_count=match_count,
            ),
            **kwargs,
        )


def test_fuse_empty_fts_orders_by_global_vector_rank():
    """Several documents, FTS empty — global vector rank decides order."""
    lists = {
        "doc-a": (
            [
                _chunk("doc-a", 0, vector_score=0.55),
            ],
            [],
        ),
        "doc-b": (
            [
                _chunk("doc-b", 0, vector_score=0.79),
            ],
            [],
        ),
        "doc-c": (
            [
                _chunk("doc-c", 0, vector_score=0.40),
            ],
            [],
        ),
    }
    fused = fuse_request_level_hybrid_rrf(
        [m for v, _ in lists.values() for m in v],
        [],
    )
    assert [m.id for m in fused] == ["doc-b:0", "doc-a:0", "doc-c:0"]
    assert fused[0].similarity > fused[1].similarity > fused[2].similarity


def test_local_rank_is_not_global_rank():
    """Per-document rank-1 must not beat another document's rank-2 when cosine differs."""
    vector = [
        _chunk("doc-a", 0, chunk_id="a1", vector_score=0.99),
        _chunk("doc-a", 1, chunk_id="a2", vector_score=0.90),
        _chunk("doc-b", 0, chunk_id="b1", vector_score=0.40),
    ]
    fused = fuse_request_level_hybrid_rrf(vector, [])
    assert [m.id for m in fused] == ["a1", "a2", "b1"]


def test_fts_can_promote_weaker_vector_candidate():
    vector = [
        _chunk("doc-a", 0, chunk_id="vec-strong", vector_score=0.95),
        _chunk("doc-b", 0, chunk_id="lex-hit", vector_score=0.50),
    ]
    keyword = [
        _chunk("doc-b", 0, chunk_id="lex-hit", full_text_score=0.90),
    ]
    fused = fuse_request_level_hybrid_rrf(vector, keyword)
    vector_ranked = ["vec-strong", "lex-hit"]
    keyword_ranked = ["lex-hit"]
    expected_scores = reciprocal_rank_fusion_scores(
        [vector_ranked, keyword_ranked],
        k=RRF_K_DEFAULT,
        limit=None,
    )
    assert fused[0].id == "lex-hit"
    assert fused[0].similarity == pytest.approx(expected_scores["lex-hit"])
    assert fused[1].similarity == pytest.approx(expected_scores["vec-strong"])


def test_single_document_fusion_matches_per_document_rrf():
    vector = [
        _chunk("doc-a", 0, chunk_id="shared", vector_score=0.90),
        _chunk("doc-a", 1, chunk_id="vec-only", vector_score=0.40),
    ]
    keyword = [
        _chunk("doc-a", 0, chunk_id="shared", full_text_score=0.80),
        _chunk("doc-a", 2, chunk_id="key-only", full_text_score=0.70),
    ]
    request_level = fuse_request_level_hybrid_rrf(vector, keyword)
    per_doc_scores = reciprocal_rank_fusion_scores(
        [
            ["shared", "vec-only"],
            ["shared", "key-only"],
        ],
        k=RRF_K_DEFAULT,
        limit=3,
    )
    per_doc_ids = list(per_doc_scores.keys())
    assert [m.id for m in request_level] == per_doc_ids
    for match in request_level:
        assert match.similarity == pytest.approx(per_doc_scores[match.id])


@pytest.mark.asyncio
async def test_cross_document_relevant_pair_stays_in_global_top_k(retrieval_env):
    lists = {
        "doc-expense": (
            [_chunk("doc-expense", 0, vector_score=0.82)],
            [],
        ),
        "doc-travel": (
            [_chunk("doc-travel", 0, vector_score=0.76)],
            [],
        ),
        "doc-noise": (
            [_chunk("doc-noise", 0, vector_score=0.30)],
            [],
        ),
    }
    result = await _retrieve_hybrid(
        list(lists),
        lists,
        match_count=2,
    )
    assert {chunk.id for chunk in result.chunks} == {"doc-expense:0", "doc-travel:0"}


@pytest.mark.asyncio
async def test_hybrid_multi_doc_orders_by_request_level_rrf_not_vector_score(retrieval_env):
    """Higher request-level RRF beats higher vector_score from another document."""
    lists = {
        "doc-a": (
            [_chunk("doc-a", 0, chunk_id="a0", vector_score=0.99)],
            [],
        ),
        "doc-b": (
            [_chunk("doc-b", 0, chunk_id="b0", vector_score=0.10)],
            [_chunk("doc-b", 0, chunk_id="b0", full_text_score=0.95)],
        ),
    }
    result = await _retrieve_hybrid(["doc-a", "doc-b"], lists)
    assert result.chunks[0].id == "b0"
    assert result.chunks[0].score_type == SCORE_TYPE_HYBRID_RRF
    assert result.chunks[0].vector_score == pytest.approx(0.10)


@pytest.mark.asyncio
async def test_vector_only_multi_document_unchanged(retrieval_env):
    chunks_by_doc = {
        "doc-a": [_chunk("doc-a", 0, similarity=0.40)],
        "doc-b": [_chunk("doc-b", 0, similarity=0.90)],
    }
    with (
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])),
        patch("services.chat_service.find_similar_chunks", new=_find_by_doc(chunks_by_doc)),
        patch(
            "services.chat_service.find_hybrid_ranked_lists",
            new=AsyncMock(side_effect=AssertionError("unexpected hybrid lists")),
        ),
    ):
        result = await retrieve_for_documents(
            "vector query",
            ["doc-a", "doc-b"],
            "dev",
            _effective(reranking_enabled=False, hybrid_enabled=False, match_count=5),
        )
    assert [chunk.id for chunk in result.chunks] == ["doc-b:0", "doc-a:0"]


@pytest.mark.asyncio
async def test_single_document_hybrid_uses_per_document_path(retrieval_env):
    hybrid_chunk = _chunk(
        "only-doc",
        0,
        similarity=0.032,
        score_type=SCORE_TYPE_HYBRID_RRF,
    )
    hybrid_chunk.rrf_score = 0.032
    find_similar = AsyncMock(return_value=[hybrid_chunk])
    find_lists = AsyncMock(side_effect=AssertionError("multi-doc path used for one doc"))
    with (
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])),
        patch("services.chat_service.find_similar_chunks", new=find_similar),
        patch("services.chat_service.find_hybrid_ranked_lists", new=find_lists),
    ):
        result = await retrieve_for_documents(
            "hybrid query",
            ["only-doc"],
            "dev",
            _effective(reranking_enabled=False, hybrid_enabled=True, match_count=5),
        )
    find_similar.assert_awaited_once()
    find_lists.assert_not_called()
    assert result.chunks[0].score_type == SCORE_TYPE_HYBRID_RRF


@pytest.mark.asyncio
async def test_fusion_before_global_cut_and_packing(retrieval_env):
    """Chunk above global cut is packed; chunk below cut is not."""
    from services.context_service import build_context_from_chunks

    lists = {
        f"doc-{idx}": ([_chunk(f"doc-{idx}", 0, vector_score=1.0 - idx * 0.05)], [])
        for idx in range(5)
    }
    cap = len(build_context_from_chunks([_chunk("doc-0", 0, vector_score=1.0)]).text)

    result = await _retrieve_hybrid(
        list(lists),
        lists,
        match_count=2,
        max_context_chars=cap,
    )
    assert [chunk.id for chunk in result.chunks] == ["doc-0:0", "doc-1:0"]
    assert [chunk.id for chunk in result.packed_chunks] == ["doc-0:0"]
    assert "doc-2:0" not in {chunk.id for chunk in result.chunks}
    assert len(result.retrieved_chunks) >= len(result.chunks)
