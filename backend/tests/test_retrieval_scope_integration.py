from unittest.mock import AsyncMock, patch

import pytest

from core.auth import AuthContext
from services import session_service
from services.chat_service import (
    answer_question_for_document,
    answer_question_stream_for_document,
    answer_questions_for_documents_batch,
)
from services.tenant_registry import clear_tenant_registry, register_tenant_document


@pytest.fixture(autouse=True)
def _reset_registries():
    session_service._SESSIONS.clear()
    clear_tenant_registry()
    yield
    session_service._SESSIONS.clear()
    clear_tenant_registry()


@pytest.fixture(autouse=True)
def _disable_query_transformation(monkeypatch):
    import services.chat_service as chat_service_mod

    monkeypatch.setattr(chat_service_mod.config, "QUERY_TRANSFORMATION_ENABLED", False)


@pytest.mark.asyncio
async def test_session_scope_searches_registered_session_document():
    session = session_service.create_session(session_id="sess-1", tenant_id="tenant-a")
    session_service.register_session_document(session.id, "doc-in-session", "tenant-a")

    with patch(
        "services.chat_service.get_embeddings",
        new=AsyncMock(return_value=[[0.1, 0.2]]),
    ), patch(
        "services.chat_service.find_similar_chunks", new=AsyncMock(return_value=[])
    ) as mock_find, patch(
        "services.chat_service.build_context_from_chunks", return_value="ctx"
    ), patch(
        "services.chat_service.generate_answer", new=AsyncMock(return_value=("answer", 0, "m"))
    ):
        result = await answer_question_for_document(
            question="Q?",
            doc_id="doc-in-session",
            session_id=session.id,
            auth=AuthContext(tenant_id="tenant-a"),
            scope="session",
        )

    assert result["status"] == "ok"
    mock_find.assert_awaited_once()
    assert mock_find.await_args.kwargs["doc_id"] == "doc-in-session"


@pytest.mark.asyncio
async def test_session_scope_blocks_document_outside_session():
    session = session_service.create_session(session_id="sess-2", tenant_id="tenant-a")
    session_service.register_session_document(session.id, "doc-allowed", "tenant-a")

    with patch(
        "services.chat_service.get_embeddings",
        new=AsyncMock(return_value=[[0.1, 0.2]]),
    ), patch(
        "services.chat_service.find_similar_chunks", new=AsyncMock(return_value=[])
    ) as mock_find, patch(
        "services.chat_service.generate_answer", new=AsyncMock(return_value="answer")
    ):
        result = await answer_question_for_document(
            question="Q?",
            doc_id="doc-blocked",
            session_id=session.id,
            auth=AuthContext(tenant_id="tenant-a"),
            scope="session",
        )

    assert result["status"] == "error"
    assert result["error"]["code"] == "no_documents_in_scope"
    mock_find.assert_not_awaited()


@pytest.mark.asyncio
async def test_tenant_scope_searches_all_tenant_documents():
    register_tenant_document("tenant-a", "doc-1")
    register_tenant_document("tenant-a", "doc-2")

    with patch(
        "services.chat_service.get_embeddings",
        new=AsyncMock(return_value=[[0.1, 0.2]]),
    ), patch(
        "services.chat_service.find_similar_chunks", new=AsyncMock(return_value=[])
    ) as mock_find, patch(
        "services.chat_service.build_context_from_chunks", return_value="ctx"
    ), patch(
        "services.chat_service.generate_answer", new=AsyncMock(return_value=("answer", 0, "m"))
    ):
        result = await answer_question_for_document(
            question="Q?",
            doc_id="doc-1",
            auth=AuthContext(tenant_id="tenant-a"),
            scope="tenant",
        )

    assert result["status"] == "ok"
    assert mock_find.await_count == 2
    searched_doc_ids = {call.kwargs["doc_id"] for call in mock_find.await_args_list}
    assert searched_doc_ids == {"doc-1", "doc-2"}


@pytest.mark.asyncio
async def test_tenant_scope_prevents_cross_tenant_document_access():
    register_tenant_document("tenant-a", "doc-a")
    register_tenant_document("tenant-b", "doc-b")

    with patch(
        "services.chat_service.get_embeddings",
        new=AsyncMock(return_value=[[0.1, 0.2]]),
    ), patch(
        "services.chat_service.find_similar_chunks", new=AsyncMock(return_value=[])
    ) as mock_find, patch(
        "services.chat_service.build_context_from_chunks", return_value="ctx"
    ), patch(
        "services.chat_service.generate_answer", new=AsyncMock(return_value=("answer", 0, "m"))
    ):
        result = await answer_question_for_document(
            question="Q?",
            doc_id="doc-b",
            auth=AuthContext(tenant_id="tenant-a"),
            scope="tenant",
        )

    assert result["status"] == "ok"
    searched_doc_ids = {call.kwargs["doc_id"] for call in mock_find.await_args_list}
    assert searched_doc_ids == {"doc-a"}
    assert "doc-b" not in searched_doc_ids


@pytest.mark.asyncio
async def test_session_scope_backward_compatible_without_session_documents():
    with patch(
        "services.chat_service.get_embeddings",
        new=AsyncMock(return_value=[[0.1, 0.2]]),
    ), patch(
        "services.chat_service.find_similar_chunks", new=AsyncMock(return_value=[])
    ) as mock_find, patch(
        "services.chat_service.build_context_from_chunks", return_value="ctx"
    ), patch(
        "services.chat_service.generate_answer", new=AsyncMock(return_value=("answer", 0, "m"))
    ):
        result = await answer_question_for_document(
            question="Q?",
            doc_id="doc-legacy",
            scope="session",
        )

    assert result["status"] == "ok"
    mock_find.assert_awaited_once_with(
        doc_id="doc-legacy",
        query_embedding=[0.1, 0.2],
        match_count=5,
        session_id=None,
        query_text="Q?",
    )


@pytest.mark.asyncio
async def test_batch_level_scope_applied_when_items_omit_scope():
    """Batch-level scope must take effect when individual items do not set their own scope."""
    register_tenant_document("tenant-a", "doc-1")
    register_tenant_document("tenant-a", "doc-2")

    queries = [
        {
            "question": "Q?",
            "doc_ids": ["doc-1"],
            "match_count": 5,
            "session_id": None,
            # no "scope" key — should inherit batch-level "tenant"
        }
    ]

    with patch(
        "services.chat_service.get_embeddings",
        new=AsyncMock(return_value=[[0.1, 0.2]]),
    ), patch(
        "services.chat_service.find_similar_chunks", new=AsyncMock(return_value=[])
    ) as mock_find, patch(
        "services.chat_service.build_context_from_chunks", return_value="ctx"
    ), patch(
        "services.chat_service.generate_answer", new=AsyncMock(return_value=("answer", 0, "m"))
    ):
        results = await answer_questions_for_documents_batch(
            queries,
            auth=AuthContext(tenant_id="tenant-a"),
            scope="tenant",
        )

    assert results[0]["status"] == "ok"
    searched_doc_ids = {call.kwargs["doc_id"] for call in mock_find.await_args_list}
    assert searched_doc_ids == {"doc-1", "doc-2"}


@pytest.mark.asyncio
async def test_stream_session_scope_blocks_document_outside_session():
    """Stream endpoint must respect session scope and block out-of-scope documents."""
    session = session_service.create_session(session_id="stream-sess", tenant_id="tenant-a")
    session_service.register_session_document(session.id, "doc-allowed", "tenant-a")

    with patch(
        "services.chat_service.get_embeddings",
        new=AsyncMock(return_value=[[0.1, 0.2]]),
    ), patch(
        "services.chat_service.find_similar_chunks", new=AsyncMock(return_value=[])
    ) as mock_find:
        events = []
        async for event in answer_question_stream_for_document(
            question="Q?",
            doc_id="doc-blocked",
            session_id=session.id,
            auth=AuthContext(tenant_id="tenant-a"),
            scope="session",
        ):
            events.append(event)

    assert any("error" in e for e in events)
    mock_find.assert_not_awaited()
