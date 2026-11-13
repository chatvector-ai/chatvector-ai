import asyncio
from fastapi import HTTPException
from unittest.mock import ANY, AsyncMock, patch

import pytest
from pydantic import ValidationError

from request_utils import make_test_request
from routes.chat import ChatBatchItem, ChatBatchRequest, ChatRequest, chat, chat_batch, chat_stream

_DOC_ID_1 = "00000000-0000-0000-0000-000000000001"
_DOC_ID_2 = "00000000-0000-0000-0000-000000000002"

from core.auth import AuthContext
from core.session import Session
from unittest.mock import ANY

_FAKE_DOC = {"id": _DOC_ID_1, "file_name": "test.pdf", "status": "completed"}
_FAKE_DOC_2 = {"id": _DOC_ID_2, "file_name": "test2.pdf", "status": "completed"}
_FAKE_SESSION = Session(id="mock-session-id", tenant_id="dev")


def test_chat_route_delegates_to_chat_service():
    payload = {"question": "q", "chunks": 1, "answer": "a"}

    with (
        patch("routes.chat.answer_question_for_document", new=AsyncMock(return_value=payload)) as mock_chat,
        patch("routes.chat.db.get_document", new=AsyncMock(return_value=_FAKE_DOC)),
        patch("routes.chat.get_or_create_session", new=AsyncMock(return_value=_FAKE_SESSION)),
        patch("routes.chat.register_session_document", new=AsyncMock()),
    ):
        result = asyncio.run(
            chat(
                make_test_request("POST", "/chat"),
                ChatRequest(question="q", doc_id=_DOC_ID_1),
                auth=AuthContext(tenant_id="dev"),
            )
        )

    assert result == payload
    mock_chat.assert_awaited_once_with(
        question="q",
        doc_id=_DOC_ID_1,
        match_count=5,
        auth=ANY,
        session_id=ANY,
        scope="session",
        debug_retrieval=False,
        retrieval_fields={},
        history_fields={},
    )

def test_chat_batch_route_delegates_to_chat_service():
    payload = {
        "count": 1,
        "success_count": 1,
        "failure_count": 0,
        "results": [{"status": "ok", "question": "q", "doc_ids": [_DOC_ID_1], "chunks": 1, "answer": "a"}],
    }
    batch_request = ChatBatchRequest(queries=[ChatBatchItem(question="q", doc_ids=[_DOC_ID_1])])

    with (
        patch(
            "routes.chat.prepare_batch_chat_items",
            new=AsyncMock(
                return_value=(
                    [
                        (
                            0,
                            {
                                "question": "q",
                                "doc_ids": [_DOC_ID_1],
                                "match_count": 5,
                                "session_id": "mock-session-id",
                            },
                        )
                    ],
                    [None],
                )
            ),
        ),
        patch(
            "routes.chat.answer_questions_for_documents_batch",
            new=AsyncMock(return_value=payload["results"]),
        ) as mock_batch,
    ):
        result = asyncio.run(
            chat_batch(make_test_request("POST", "/chat/batch"), batch_request, auth=AuthContext(tenant_id="dev"))
        )

    assert result == payload
    mock_batch.assert_awaited_once_with(
        [{"question": "q", "doc_ids": [_DOC_ID_1], "match_count": 5, "session_id": ANY}],
        auth=ANY,
        scope=None,
        debug_retrieval=False,
    )


def test_chat_batch_route_counts_failures_and_successes():
    batch_request = ChatBatchRequest(queries=[ChatBatchItem(question="q", doc_ids=[_DOC_ID_1])])

    with (
        patch(
            "routes.chat.prepare_batch_chat_items",
            new=AsyncMock(
                return_value=(
                    [
                        (0, {"question": "q1", "doc_ids": [_DOC_ID_1], "match_count": 5, "session_id": "mock-session-id"}),
                        (1, {"question": "q2", "doc_ids": [_DOC_ID_2], "match_count": 5, "session_id": "mock-session-id"}),
                    ],
                    [None, None],
                )
            ),
        ),
        patch(
            "routes.chat.answer_questions_for_documents_batch",
            new=AsyncMock(
                return_value=[
                    {"status": "ok", "question": "q1", "doc_ids": [_DOC_ID_1], "chunks": 1, "answer": "a1"},
                    {
                        "status": "error",
                        "question": "q2",
                        "doc_ids": [_DOC_ID_2],
                        "chunks": 0,
                        "error": {"code": "query_processing_failed", "message": "boom"},
                    },
                ]
            ),
        ),
    ):
        result = asyncio.run(
            chat_batch(make_test_request("POST", "/chat/batch"), batch_request, auth=AuthContext(tenant_id="dev"))
        )

    assert result["count"] == 2
    assert result["success_count"] == 1
    assert result["failure_count"] == 1


def test_chat_batch_route_returns_422_for_value_error():
    batch_request = ChatBatchRequest(queries=[ChatBatchItem(question="q", doc_ids=[_DOC_ID_1])])

    with patch(
        "routes.chat.prepare_batch_chat_items",
        new=AsyncMock(side_effect=ValueError("invalid payload")),
    ):
        try:
            asyncio.run(
                chat_batch(make_test_request("POST", "/chat/batch"), batch_request, auth=AuthContext(tenant_id="dev"))
            )
            raise AssertionError("Expected HTTPException was not raised")
        except HTTPException as exc:
            assert exc.status_code == 422
            assert exc.detail["code"] == "invalid_batch_request"


def test_chat_route_rejects_invalid_scope():
    with pytest.raises(ValidationError, match="scope"):
        ChatRequest(question="q", doc_id=_DOC_ID_1, scope="global")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_chat_stream_route_disabled():
    with patch("routes.chat.config") as mock_config:
        mock_config.ENABLE_STREAMING = False
        with pytest.raises(HTTPException) as exc_info:
            await chat_stream(
                make_test_request("POST", "/chat/stream"),
                ChatRequest(question="q", doc_id=_DOC_ID_1),
                auth=AuthContext(tenant_id="dev"),
            )
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "streaming_disabled"

@pytest.mark.asyncio
async def test_chat_stream_route_enabled():
    async def mock_stream(*args, **kwargs):
        yield "event: token\ndata: \"Hello\"\n\n"
        yield "event: done\ndata: [DONE]\n\n"

    with (
        patch("routes.chat.config") as mock_config,
        patch("routes.chat.answer_question_stream_for_document", new=mock_stream) as mock_answer,
        patch("routes.chat.db.get_document", new=AsyncMock(return_value=_FAKE_DOC)),
        patch("routes.chat.get_or_create_session", new=AsyncMock(return_value=_FAKE_SESSION)),
        patch("routes.chat.register_session_document", new=AsyncMock()),
    ):
        mock_config.ENABLE_STREAMING = True
        response = await chat_stream(
            make_test_request("POST", "/chat/stream"),
            ChatRequest(question="q", doc_id=_DOC_ID_1),
            auth=AuthContext(tenant_id="dev"),
        )

        assert response.media_type == "text/event-stream"
        
        # Read streaming response chunks
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        assert len(chunks) == 2
        assert chunks[0] == "event: token\ndata: \"Hello\"\n\n"
        assert chunks[1] == "event: done\ndata: [DONE]\n\n"


def test_chat_route_returns_200_for_embedding_auth_failure():
    """Route-level sync: embedding auth maps to HTTP 200 status=error, not 500."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.auth import require_auth
    from main import global_exception_handler
    from middleware.rate_limit import limiter
    from routes.chat import router as chat_router
    from services.chat_service import EMBEDDING_INVALID_API_KEY_MESSAGE
    from services.providers.base import ProviderAuthError

    limiter.reset()
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(Exception, global_exception_handler)
    app.dependency_overrides[require_auth] = lambda: AuthContext(tenant_id="dev")
    app.include_router(chat_router)

    payload = {"question": "q", "doc_id": _DOC_ID_1, "match_count": 5}
    with (
        TestClient(app, raise_server_exceptions=False) as client,
        patch("routes.chat.db.get_document", new=AsyncMock(return_value=_FAKE_DOC)),
        patch("routes.chat.get_or_create_session", new=AsyncMock(return_value=_FAKE_SESSION)),
        patch("routes.chat.register_session_document", new=AsyncMock()),
        patch("routes.chat.register_tenant_document"),
        patch(
            "services.chat_service._resolve_retrieval_doc_ids",
            new=AsyncMock(return_value=[_DOC_ID_1]),
        ),
        patch(
            "services.chat_service.get_embeddings",
            new=AsyncMock(side_effect=ProviderAuthError("401 invalid")),
        ),
    ):
        response = client.post("/chat", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert body["error"] == {
        "code": "embedding_invalid_api_key",
        "message": EMBEDDING_INVALID_API_KEY_MESSAGE,
    }
    limiter.reset()


def test_chat_route_embedding_failure_returns_internal_error():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.auth import require_auth
    from main import global_exception_handler
    from middleware.rate_limit import limiter
    from routes.chat import router as chat_router

    limiter.reset()
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(Exception, global_exception_handler)
    app.dependency_overrides[require_auth] = lambda: AuthContext(tenant_id="dev")
    app.include_router(chat_router)

    payload = {"question": "q", "doc_id": _DOC_ID_1, "match_count": 5}
    with (
        TestClient(app, raise_server_exceptions=False) as client,
        patch("routes.chat.db.get_document", new=AsyncMock(return_value=_FAKE_DOC)),
        patch("routes.chat.get_or_create_session", new=AsyncMock(return_value=_FAKE_SESSION)),
        patch("routes.chat.register_session_document", new=AsyncMock()),
        patch("routes.chat.register_tenant_document"),
        patch(
            "services.chat_service._resolve_retrieval_doc_ids",
            new=AsyncMock(return_value=[_DOC_ID_1]),
        ),
        patch(
            "services.chat_service.get_embeddings",
            new=AsyncMock(side_effect=RuntimeError("embed down")),
        ),
    ):
        response = client.post("/chat", json=payload)

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "internal_error"
    limiter.reset()
