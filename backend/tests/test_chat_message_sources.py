"""Answer-time source snapshots on assistant chat messages (issue 596)."""

from __future__ import annotations

import sys
import uuid
from unittest.mock import AsyncMock, patch

import pytest

import services.chat_service as chat_service_mod
from core.auth import AuthContext
from db.base import ChunkMatch, ChunkRecord
from services.chat_service import (
    _build_source_snapshot,
    _build_sources,
    answer_question_for_document,
    answer_question_stream_for_document,
    answer_questions_for_documents_batch,
)
from services.query_service import QueryTransformResult

TEST_AUTH = AuthContext(tenant_id="dev")

SNAPSHOT = [
    {
        "document_id": "11111111-1111-1111-1111-111111111111",
        "file_name": "handbook-v1.pdf",
        "page_number": 3,
        "chunk_index": 2,
        "score": 0.91,
        "score_type": "vector",
        "page_end": 5,
    }
]


def _mock_transform_result(question: str) -> QueryTransformResult:
    return QueryTransformResult(queries=[question], original_query=question)


async def _passthrough_retrieval_doc_ids(**kwargs):
    return list(kwargs["requested_doc_ids"])


@pytest.fixture(autouse=True)
def _passthrough_retrieval_scope(monkeypatch):
    monkeypatch.setattr(
        chat_service_mod,
        "_resolve_retrieval_doc_ids",
        _passthrough_retrieval_doc_ids,
    )


@pytest.fixture(autouse=True)
def _disable_query_transformation(monkeypatch):
    monkeypatch.setattr(
        chat_service_mod.config, "QUERY_TRANSFORMATION_ENABLED", False
    )


async def _fresh_service():
    pytest.importorskip("pgvector")
    if sys.platform == "win32":
        pytest.skip("Psycopg async mode not supported with ProactorEventLoop on Windows")
    from db.sqlalchemy_service import SQLAlchemyService

    return SQLAlchemyService()


@pytest.fixture()
async def svc():
    service = await _fresh_service()
    yield service
    try:
        await service.engine.dispose()
    except Exception:
        pass


def _unit_vector(position: int = 0) -> list[float]:
    from core.config import get_embedding_dim

    vector = [0.0] * get_embedding_dim()
    vector[position] = 1.0
    return vector


def test_build_source_snapshot_adds_document_id_beside_live_sources():
    chunk = ChunkMatch(
        id="c1",
        chunk_text="secret chunk text",
        document_id="doc-42",
        file_name="notes.pdf",
        page_number=4,
        chunk_index=1,
        similarity=0.77,
        score_type="vector",
        vector_score=0.77,
    )

    live = _build_sources([chunk])
    snapshot = _build_source_snapshot([chunk])

    assert "document_id" not in live[0]
    assert snapshot == [
        {
            "file_name": "notes.pdf",
            "page_number": 4,
            "chunk_index": 1,
            "score": 0.77,
            "score_type": "vector",
            "vector_score": 0.77,
            "document_id": "doc-42",
        }
    ]
    assert "chunk_text" not in snapshot[0]


def test_build_source_snapshot_empty_chunks_is_empty_list():
    assert _build_source_snapshot([]) == []


def test_build_source_snapshot_reuses_live_sources_without_rebuilding():
    chunk = ChunkMatch(
        id="c1",
        chunk_text="cited text",
        document_id="doc-1",
        file_name="notes.pdf",
        page_number=1,
        chunk_index=0,
        similarity=0.5,
        score_type="vector",
    )
    live = _build_sources([chunk])
    live[0]["page_end"] = 3

    snapshot = _build_source_snapshot([chunk], live)

    assert snapshot[0]["page_end"] == 3
    assert snapshot[0]["document_id"] == "doc-1"
    assert "document_id" not in live[0]


@pytest.mark.asyncio
async def test_store_chat_turn_writes_assistant_snapshot_and_null_user(svc):
    session_id = f"src-{uuid.uuid4()}"
    tenant_id = f"tenant-{uuid.uuid4()}"
    await svc.create_session_record(session_id, tenant_id)

    await svc.store_chat_turn(
        session_id, "question", "answer", tenant_id, sources=SNAPSHOT
    )
    history = await svc.get_session_history(session_id, tenant_id)

    assert history[0]["role"] == "user"
    assert history[0]["sources"] is None
    assert history[1]["role"] == "assistant"
    assert history[1]["sources"] == SNAPSHOT
    assert history[1]["sources"][0]["page_end"] == 5
    assert "chunk_text" not in history[1]["sources"][0]
    assert "retrieval_debug" not in history[1]["sources"][0]
    assert "session_history" not in history[1]["sources"][0]

    await svc.delete_session_record(session_id, tenant_id)


@pytest.mark.asyncio
async def test_store_chat_turn_empty_sources_stays_empty_list(svc):
    session_id = f"src-empty-{uuid.uuid4()}"
    tenant_id = f"tenant-{uuid.uuid4()}"
    await svc.create_session_record(session_id, tenant_id)

    await svc.store_chat_turn(session_id, "q", "a", tenant_id, sources=[])
    history = await svc.get_session_history(session_id, tenant_id)

    assert history[0]["sources"] is None
    assert history[1]["sources"] == []

    await svc.delete_session_record(session_id, tenant_id)


@pytest.mark.asyncio
async def test_store_chat_turn_default_and_pre_snapshot_rows_are_null(svc):
    session_id = f"src-null-{uuid.uuid4()}"
    tenant_id = f"tenant-{uuid.uuid4()}"
    await svc.create_session_record(session_id, tenant_id)

    await svc.store_chat_turn(session_id, "q", "a", tenant_id)
    history = await svc.get_session_history(session_id, tenant_id)

    assert history[0]["sources"] is None
    assert history[1]["sources"] is None

    await svc.delete_session_record(session_id, tenant_id)


@pytest.mark.asyncio
async def test_replace_document_does_not_mutate_stored_sources(svc):
    from services.api_key_service import create_tenant

    tenant_id = f"src-replace-{uuid.uuid4().hex[:8]}"
    await create_tenant("Source snapshot replacement", tenant_id=tenant_id)
    session_id = f"src-replace-{uuid.uuid4()}"
    await svc.create_session_record(session_id, tenant_id)

    doc_id = await svc.create_document("handbook-v1.pdf", tenant_id=tenant_id)
    await svc.store_chunks_with_embeddings(
        doc_id,
        [
            ChunkRecord(
                chunk_text="old edition",
                embedding=_unit_vector(0),
                chunk_index=0,
                character_offset_start=0,
                character_offset_end=11,
                page_number=3,
            )
        ],
        tenant_id,
    )
    await svc.update_document_status(
        doc_id,
        "completed",
        tenant_id=tenant_id,
        chunks={"total": 1, "processed": 1},
    )

    snapshot = [
        {
            "document_id": doc_id,
            "file_name": "handbook-v1.pdf",
            "page_number": 3,
            "chunk_index": 0,
            "score": 0.88,
        }
    ]
    await svc.store_chat_turn(
        session_id, "What is PTO?", "Fifteen days.", tenant_id, sources=snapshot
    )

    await svc.replace_document_content(
        doc_id,
        [
            ChunkRecord(
                chunk_text="new edition",
                embedding=_unit_vector(1),
                chunk_index=0,
                character_offset_start=0,
                character_offset_end=11,
                page_number=9,
            )
        ],
        tenant_id,
        file_name="handbook-v2.pdf",
    )

    history = await svc.get_session_history(session_id, tenant_id)
    assert history[1]["sources"] == snapshot
    document = await svc.get_document(doc_id, tenant_id)
    assert document["file_name"] == "handbook-v2.pdf"

    await svc.delete_session_record(session_id, tenant_id)


def _chunk(document_id: str = "doc-1") -> ChunkMatch:
    return ChunkMatch(
        id="c1",
        chunk_text="cited text",
        document_id=document_id,
        file_name="report.pdf",
        page_number=2,
        chunk_index=0,
        similarity=0.85,
        score_type="vector",
    )


@pytest.mark.asyncio
async def test_non_streaming_chat_passes_source_snapshot():
    with (
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])),
        patch(
            "services.chat_service._retrieve_chunks_for_documents",
            new=AsyncMock(return_value=[_chunk("doc-live")]),
        ),
        patch("services.chat_service.build_context_from_chunks", return_value="ctx"),
        patch(
            "services.chat_service.generate_answer",
            new=AsyncMock(return_value=("answer", 10, "test-model")),
        ),
        patch("db.get_session_history", new=AsyncMock(return_value=[])),
        patch("db.store_chat_turn", new=AsyncMock()) as mock_store,
    ):
        await answer_question_for_document(
            question="Q",
            doc_id="doc-live",
            session_id="sess-1",
            auth=TEST_AUTH,
        )

    assert mock_store.await_count == 1
    assert mock_store.await_args.kwargs["sources"] == _build_source_snapshot(
        [_chunk("doc-live")]
    )
    assert mock_store.await_args.kwargs["sources"][0]["document_id"] == "doc-live"
    assert "chunk_text" not in mock_store.await_args.kwargs["sources"][0]


@pytest.mark.asyncio
async def test_non_streaming_chat_passes_empty_snapshot_when_no_chunks():
    with (
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])),
        patch(
            "services.chat_service._retrieve_chunks_for_documents",
            new=AsyncMock(return_value=[]),
        ),
        patch("services.chat_service.build_context_from_chunks", return_value=""),
        patch(
            "services.chat_service.generate_answer",
            new=AsyncMock(return_value=("answer", 10, "test-model")),
        ),
        patch("db.get_session_history", new=AsyncMock(return_value=[])),
        patch("db.store_chat_turn", new=AsyncMock()) as mock_store,
    ):
        await answer_question_for_document(
            question="Q",
            doc_id="doc-1",
            session_id="sess-empty",
            auth=TEST_AUTH,
        )

    assert mock_store.await_args.kwargs["sources"] == []


@pytest.mark.asyncio
async def test_stream_path_passes_source_snapshot():
    async def mock_generate_stream(q, c):
        yield "token"

    with (
        patch(
            "services.chat_service._resolve_retrieval_doc_ids",
            new=AsyncMock(return_value=["doc-1"]),
        ),
        patch(
            "services.chat_service.transform_query",
            new=AsyncMock(return_value=_mock_transform_result("Q")),
        ),
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])),
        patch(
            "services.chat_service._retrieve_chunks_for_documents",
            new=AsyncMock(return_value=[_chunk()]),
        ),
        patch("services.chat_service.build_context_from_chunks", return_value="ctx"),
        patch("services.chat_service.generate_answer_stream", new=mock_generate_stream),
        patch("db.get_session_history", new=AsyncMock(return_value=[])),
        patch(
            "db.store_chat_turn",
            new=AsyncMock(return_value=("user-msg", "assistant-msg")),
        ) as mock_store,
    ):
        async for _ in answer_question_stream_for_document(
            "Q?", "doc-1", session_id="sess-stream", auth=TEST_AUTH
        ):
            pass

    assert mock_store.await_args.kwargs["sources"] == _build_source_snapshot([_chunk()])


@pytest.mark.asyncio
async def test_persisted_batch_passes_source_snapshot():
    with (
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])),
        patch(
            "services.chat_service._retrieve_chunks_for_documents",
            new=AsyncMock(return_value=[_chunk("doc-a")]),
        ),
        patch("services.chat_service.build_context_from_chunks", return_value="ctx"),
        patch(
            "services.chat_service.generate_answer",
            new=AsyncMock(return_value=("answer", 10, "test-model")),
        ),
        patch("db.get_session_history", new=AsyncMock(return_value=[])),
        patch("db.store_chat_turn", new=AsyncMock()) as mock_store,
    ):
        await answer_questions_for_documents_batch(
            [
                {
                    "question": "Summarize",
                    "doc_ids": ["doc-a", "doc-b"],
                    "session_id": "sess-batch",
                }
            ],
            auth=TEST_AUTH,
        )

    assert mock_store.await_count == 1
    assert mock_store.await_args.kwargs["sources"] == _build_source_snapshot(
        [_chunk("doc-a")]
    )


@pytest.mark.asyncio
async def test_compare_style_batch_does_not_store_a_turn():
    with (
        patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]])),
        patch(
            "services.chat_service._retrieve_chunks_for_documents",
            new=AsyncMock(return_value=[_chunk()]),
        ),
        patch("services.chat_service.build_context_from_chunks", return_value="ctx"),
        patch(
            "services.chat_service.generate_answer",
            new=AsyncMock(return_value=("answer", 10, "test-model")),
        ),
        patch("db.get_session_history", new=AsyncMock(return_value=[])),
        patch("db.store_chat_turn", new=AsyncMock()) as mock_store,
    ):
        await answer_questions_for_documents_batch(
            [
                {
                    "question": "Compare me",
                    "doc_ids": ["doc-1"],
                    "session_id": "sess-compare",
                }
            ],
            auth=TEST_AUTH,
        )

    mock_store.assert_not_awaited()
