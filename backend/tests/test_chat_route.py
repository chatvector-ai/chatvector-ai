import asyncio
from fastapi import HTTPException
from unittest.mock import AsyncMock, patch

from routes.chat import ChatBatchItem, ChatBatchRequest, chat, chat_batch


def test_chat_route_delegates_to_chat_service():
    payload = {"question": "q", "chunks": 1, "answer": "a"}

    with patch("routes.chat.answer_question_for_document", new=AsyncMock(return_value=payload)) as mock_chat:
        result = asyncio.run(chat(question="q", doc_id="doc-xyz"))

    assert result == payload
    mock_chat.assert_awaited_once_with(question="q", doc_id="doc-xyz", match_count=5)


def test_chat_batch_route_delegates_to_chat_service():
    payload = {"count": 1, "results": [{"question": "q", "doc_ids": ["doc-1"], "chunks": 1, "answer": "a"}]}
    batch_request = ChatBatchRequest(queries=[ChatBatchItem(question="q", doc_ids=["doc-1"])])

    with patch(
        "routes.chat.answer_questions_for_documents_batch",
        new=AsyncMock(return_value=payload["results"]),
    ) as mock_batch:
        result = asyncio.run(chat_batch(batch_request))

    assert result == payload
    mock_batch.assert_awaited_once_with(
        [{"question": "q", "doc_ids": ["doc-1"], "match_count": 5}]
    )


def test_chat_batch_route_returns_422_for_value_error():
    batch_request = ChatBatchRequest(queries=[ChatBatchItem(question="q", doc_ids=["doc-1"])])

    with patch(
        "routes.chat.answer_questions_for_documents_batch",
        new=AsyncMock(side_effect=ValueError("invalid payload")),
    ):
        try:
            asyncio.run(chat_batch(batch_request))
            raise AssertionError("Expected HTTPException was not raised")
        except HTTPException as exc:
            assert exc.status_code == 422
            assert exc.detail["code"] == "invalid_batch_request"
