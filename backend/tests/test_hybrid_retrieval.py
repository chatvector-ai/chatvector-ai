"""Tests for hybrid retrieval (RRF, config toggle, PostgreSQL full-text)."""

import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from core.config import config
from db.base import ChunkMatch
from services.retrieval_service import merge_chunk_matches, reciprocal_rank_fusion


def test_reciprocal_rank_fusion_prefers_items_in_both_lists():
    vector_ranked = ["a", "b", "c"]
    keyword_ranked = ["b", "d", "e"]
    fused = reciprocal_rank_fusion([vector_ranked, keyword_ranked], limit=3)
    assert fused == ["b", "a", "d"]


def test_reciprocal_rank_fusion_respects_limit():
    fused = reciprocal_rank_fusion([["x", "y", "z"]], limit=2)
    assert fused == ["x", "y"]


def test_merge_chunk_matches_preserves_fused_order():
    matches = {
        "1": ChunkMatch(id="1", chunk_text="one"),
        "2": ChunkMatch(id="2", chunk_text="two"),
    }
    merged = merge_chunk_matches(["2", "1"], matches)
    assert [m.id for m in merged] == ["2", "1"]


@pytest.mark.asyncio
async def test_find_similar_chunks_vector_only_when_hybrid_disabled():
    pytest.importorskip("pgvector")
    from db.sqlalchemy_service import SQLAlchemyService

    service = SQLAlchemyService()
    service._retrieval_semaphore = __import__("asyncio").Semaphore(10)
    service._find_keyword_chunks = AsyncMock(return_value=[])

    vector_match = ChunkMatch(id="vec-1", chunk_text="vector chunk")
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
            match_count=5,
            query_text="exact keyword",
        )

    assert results == [vector_match]
    service._find_keyword_chunks.assert_not_called()
    service._find_vector_chunks.assert_called_once()


@pytest.mark.asyncio
async def test_find_similar_chunks_hybrid_invokes_both_paths():
    pytest.importorskip("pgvector")
    from db.sqlalchemy_service import SQLAlchemyService

    service = SQLAlchemyService()
    service._retrieval_semaphore = __import__("asyncio").Semaphore(10)

    vector_match = ChunkMatch(id="vec-1", chunk_text="alpha")
    keyword_match = ChunkMatch(id="key-1", chunk_text="beta")
    service._find_vector_chunks = AsyncMock(return_value=[vector_match])
    service._find_keyword_chunks = AsyncMock(return_value=[keyword_match])

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
            match_count=5,
            query_text="beta",
        )

    service._find_vector_chunks.assert_called_once()
    service._find_keyword_chunks.assert_called_once()
    assert {m.id for m in results} == {"vec-1", "key-1"}


@pytest.mark.asyncio
async def test_find_similar_chunks_hybrid_fusion_order():
    pytest.importorskip("pgvector")
    from db.sqlalchemy_service import SQLAlchemyService

    service = SQLAlchemyService()
    service._retrieval_semaphore = __import__("asyncio").Semaphore(10)

    shared = ChunkMatch(id="shared", chunk_text="both lists")
    vec_only = ChunkMatch(id="vec-only", chunk_text="vector")
    key_only = ChunkMatch(id="key-only", chunk_text="keyword")
    service._find_vector_chunks = AsyncMock(return_value=[shared, vec_only])
    service._find_keyword_chunks = AsyncMock(return_value=[shared, key_only])

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
            match_count=3,
            query_text="lookup",
        )

    assert [m.id for m in results] == ["shared", "vec-only", "key-only"]


@pytest.mark.asyncio
async def test_find_keyword_chunks_returns_empty_when_column_missing():
    pytest.importorskip("pgvector")
    from sqlalchemy.exc import ProgrammingError

    from db.sqlalchemy_service import SQLAlchemyService

    service = SQLAlchemyService()

    class _FakeSession:
        async def execute(self, *args, **kwargs):
            raise ProgrammingError(
                "stmt",
                {},
                Exception('column "content_tsv" does not exist'),
            )

    results = await service._find_keyword_chunks(_FakeSession(), "doc-1", "keyword", 5)
    assert results == []


@pytest.mark.asyncio
async def test_hybrid_keyword_finds_exact_term_integration():
    """Keyword path retrieves chunks containing an exact rare token."""
    if sys.platform == "win32":
        pytest.skip("Psycopg async mode not supported with ProactorEventLoop on Windows")

    pytest.importorskip("pgvector")
    from sqlalchemy import text

    from core.config import get_embedding_dim
    from db.base import ChunkRecord
    from db.sqlalchemy_service import SQLAlchemyService

    db = SQLAlchemyService()
    migration_path = (
        Path(__file__).resolve().parents[1] / "db" / "init" / "004_hybrid_retrieval.sql"
    )
    migration_sql = migration_path.read_text(encoding="utf-8")
    async with db.engine.begin() as conn:
        for statement in migration_sql.split(";"):
            stmt = statement.strip()
            if stmt:
                await conn.execute(text(stmt))

    dim = get_embedding_dim()
    filler = [0.0] * dim
    filler[0] = 1.0
    unique_token = f"HYBRID-EXACT-{uuid.uuid4().hex[:8]}"
    file_name = f"hybrid_test_{uuid.uuid4()}.pdf"

    doc_id = await db.create_document(file_name)
    await db.store_chunks_with_embeddings(
        doc_id,
        [
            ChunkRecord(
                chunk_text=f"Intro paragraph without special terms.",
                embedding=filler,
                chunk_index=0,
                character_offset_start=0,
                character_offset_end=40,
            ),
            ChunkRecord(
                chunk_text=f"Section referencing {unique_token} for lookup.",
                embedding=filler,
                chunk_index=1,
                character_offset_start=41,
                character_offset_end=80,
            ),
        ],
    )

    with patch.object(config, "HYBRID_RETRIEVAL_ENABLED", True):
        matches = await db.find_similar_chunks(
            doc_id,
            filler,
            match_count=5,
            query_text=unique_token,
        )

    assert any(unique_token in (m.chunk_text or "") for m in matches)
