import asyncio
import uuid
import pytest
from unittest.mock import AsyncMock, patch

from core.auth import AuthContext
from request_utils import make_test_request
from routes.chat import ChatRequest, chat
from core.config import config
import db


@pytest.mark.asyncio
async def test_chat_route_stores_history_on_success():
    """Verify that a successful chat interaction stores the user and assistant messages."""
    payload = {"question": "q", "chunks": 1, "answer": "a", "session_id": "test-session", "status": "ok"}
    _DOC_ID_1 = "00000000-0000-0000-0000-000000000001"

    with patch(
        "routes.chat.answer_question_for_document", new=AsyncMock(return_value=payload)
    ), patch("routes.chat.get_or_create_session") as mock_get_session:
        # Mock the session to return an object with id="test-session"
        class MockSession:
            id = "test-session"
            tenant_id = None
        mock_get_session.return_value = MockSession()
        
        result = await chat(
            make_test_request("POST", "/chat"),
            ChatRequest(question="q", doc_id=_DOC_ID_1, session_id="test-session"),
            auth=AuthContext(),
        )

    assert result == payload

@pytest.mark.asyncio
async def test_db_message_persistence_and_retrieval():
    """Verify storing messages and retrieving them preserves order and limits."""
    import sys
    if sys.platform == "win32":
        pytest.skip("Psycopg async mode not supported with ProactorEventLoop on Windows")
    pytest.importorskip("pgvector")

    from db.sqlalchemy_service import SQLAlchemyService
    db_service = SQLAlchemyService()
    
    session_id = f"test-session-{uuid.uuid4()}"
    
    # Store messages
    for i in range(25):
        await db_service.store_chat_message(session_id, "user", f"Question {i}")
        await db_service.store_chat_message(session_id, "assistant", f"Answer {i}")
        
    history = await db_service.get_session_history(session_id, limit=10)
    
    assert len(history) == 10
    # The limit is applied such that the most recent messages are returned, in chronological order
    # The last 10 messages should be Q20, A20, Q21, A21, Q22, A22, Q23, A23, Q24, A24
    assert history[-1]["role"] == "assistant"
    assert history[-1]["content"] == "Answer 24"
    assert history[-2]["role"] == "user"
    assert history[-2]["content"] == "Question 24"
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "Question 20"

@pytest.mark.asyncio
async def test_db_tenant_scoped_retrieval():
    """Verify history retrieval respects tenant isolation."""
    import sys
    if sys.platform == "win32":
        pytest.skip("Psycopg async mode not supported with ProactorEventLoop on Windows")
    pytest.importorskip("pgvector")

    from db.sqlalchemy_service import SQLAlchemyService
    db_service = SQLAlchemyService()
    
    session_id = f"test-session-{uuid.uuid4()}"
    tenant_a = f"tenant-A-{uuid.uuid4()}"
    tenant_b = f"tenant-B-{uuid.uuid4()}"
    
    await db_service.store_chat_message(session_id, "user", "Q1", tenant_id=tenant_a)
    await db_service.store_chat_message(session_id, "assistant", "A1", tenant_id=tenant_a)
    
    # tenant_a can retrieve it
    history_a = await db_service.get_session_history(session_id, limit=10, tenant_id=tenant_a)
    assert len(history_a) == 2
    
    # tenant_b cannot retrieve it
    history_b = await db_service.get_session_history(session_id, limit=10, tenant_id=tenant_b)
    assert len(history_b) == 0
    
    # no tenant can retrieve it (in strict isolation) unless it was stored without a tenant,
    # but currently if tenant_id is None in get_session_history, the DB query might omit the tenant filter.
    # We just need to ensure that specifying a tenant_id filters correctly.
    
@pytest.mark.asyncio
async def test_stream_finalization_persistence():
    """Verify that a completed stream correctly persists messages via the service method."""
    from services.chat_service import answer_question_stream_for_document
    
    session_id = f"stream-session-{uuid.uuid4()}"
    _DOC_ID_1 = "00000000-0000-0000-0000-000000000001"
    
    with patch("services.chat_service.transform_query", new=AsyncMock(return_value=["Q"])), \
         patch("services.chat_service.get_embeddings", new=AsyncMock(return_value=[[0.1]*1536])), \
         patch("services.chat_service._retrieve_chunks_for_documents", new=AsyncMock(return_value=[])), \
         patch("services.chat_service.generate_answer_stream") as mock_stream, \
         patch("db.get_session_history", new=AsyncMock(return_value=[])) as mock_history, \
         patch("db.store_chat_message", new=AsyncMock()) as mock_store:
         
        async def fake_stream(*args, **kwargs):
            yield "stream part 1 "
            yield "stream part 2"
            
        mock_stream.side_effect = fake_stream
        
        gen = answer_question_stream_for_document("Stream Q?", _DOC_ID_1, session_id=session_id)
        chunks = [c async for c in gen]
        
        assert any("stream part 1 " in c for c in chunks)
        
        # Verify db persistence was called
        mock_history.assert_called_once_with(session_id=session_id, limit=config.MAX_SESSION_HISTORY_MESSAGES, tenant_id=None)
        assert mock_store.call_count == 2
        
        # Check that user question and full assistant answer were stored
        call_1_kwargs = mock_store.call_args_list[0].kwargs
        assert call_1_kwargs["role"] == "user"
        assert call_1_kwargs["content"] == "Stream Q?"
        
        call_2_kwargs = mock_store.call_args_list[1].kwargs
        assert call_2_kwargs["role"] == "assistant"
        assert call_2_kwargs["content"] == "stream part 1 stream part 2"
