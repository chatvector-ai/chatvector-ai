import asyncio
from fastapi import HTTPException
from unittest.mock import AsyncMock, patch

from request_utils import make_test_request
from routes.chat import ChatBatchItem, ChatBatchRequest, ChatRequest, chat, chat_batch

_DOC_ID_1 = "00000000-0000-0000-0000-000000000001"
_DOC_ID_2 = "00000000-0000-0000-0000-000000000002"

from core.auth import AuthContext
from unittest.mock import ANY

def test_chat_route_delegates_to_chat_service():
    payload = {"question": "q", "chunks": 1, "answer": "a"}

    with patch("routes.chat.answer_question_for_document", new=AsyncMock(return_value=payload)) as mock_chat:
        result = asyncio.run(
            chat(
                make_test_request("POST", "/chat"),
                ChatRequest(question="q", doc_id=_DOC_ID_1),
                auth=AuthContext(),
            )
        )

    assert result == payload
    mock_chat.assert_awaited_once_with(question="q", doc_id=_DOC_ID_1, match_count=5, auth=ANY)

def test_chat_batch_route_delegates_to_chat_service():
    payload = {
        "count": 1,
        "success_count": 1,
        "failure_count": 0,
        "results": [{"status": "ok", "question": "q", "doc_ids": [_DOC_ID_1], "chunks": 1, "answer": "a"}],
    }
    batch_request = ChatBatchRequest(queries=[ChatBatchItem(question="q", doc_ids=[_DOC_ID_1])])

    with patch(
        "routes.chat.answer_questions_for_documents_batch",
        new=AsyncMock(return_value=payload["results"]),
    ) as mock_batch:
        result = asyncio.run(
            chat_batch(make_test_request("POST", "/chat/batch"), batch_request, auth=AuthContext())
        )

    assert result == payload
    mock_batch.assert_awaited_once_with(
        [{"question": "q", "doc_ids": [_DOC_ID_1], "match_count": 5}], auth=ANY
    )


def test_chat_batch_route_counts_failures_and_successes():
    batch_request = ChatBatchRequest(queries=[ChatBatchItem(question="q", doc_ids=[_DOC_ID_1])])

    with patch(
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
    ):
        result = asyncio.run(
            chat_batch(make_test_request("POST", "/chat/batch"), batch_request, auth=AuthContext())
        )

    assert result["count"] == 2
    assert result["success_count"] == 1
    assert result["failure_count"] == 1


def test_chat_batch_route_returns_422_for_value_error():
    batch_request = ChatBatchRequest(queries=[ChatBatchItem(question="q", doc_ids=[_DOC_ID_1])])

    with patch(
        "routes.chat.answer_questions_for_documents_batch",
        new=AsyncMock(side_effect=ValueError("invalid payload")),
    ):
        try:
            asyncio.run(
                chat_batch(make_test_request("POST", "/chat/batch"), batch_request, auth=AuthContext())
            )
            raise AssertionError("Expected HTTPException was not raised")
        except HTTPException as exc:
            assert exc.status_code == 422
            assert exc.detail["code"] == "invalid_batch_request"

import pytest
from routes.chat import chat_stream

@pytest.mark.asyncio
async def test_chat_stream_route_disabled():
    with patch("routes.chat.config") as mock_config:
        mock_config.ENABLE_STREAMING = False
        with pytest.raises(HTTPException) as exc_info:
            await chat_stream(
                make_test_request("POST", "/chat/stream"),
                ChatRequest(question="q", doc_id=_DOC_ID_1),
                auth=AuthContext(),
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
        patch("routes.chat.answer_question_stream_for_document", new=mock_stream) as mock_answer
    ):
        mock_config.ENABLE_STREAMING = True
        response = await chat_stream(
            make_test_request("POST", "/chat/stream"),
            ChatRequest(question="q", doc_id=_DOC_ID_1),
            auth=AuthContext(),
        )

        assert response.media_type == "text/event-stream"
        
        # Read streaming response chunks
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        assert len(chunks) == 2
        assert chunks[0] == "event: token\ndata: \"Hello\"\n\n"
        assert chunks[1] == "event: done\ndata: [DONE]\n\n"

