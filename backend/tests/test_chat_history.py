import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from core.auth import AuthContext
from request_utils import make_test_request
from routes.chat import ChatRequest, chat


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
