"""422 responses for chat route request body validation (Pydantic bounds)."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from middleware.rate_limit import limiter
from routes.chat import router as chat_router


async def _rate_limit_exceeded_handler(
    _request: Request, _exc: RateLimitExceeded
) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={
            "detail": {
                "code": "rate_limited",
                "message": "Too many requests. Please slow down.",
            }
        },
        headers={"Retry-After": "60"},
    )


def _chat_validation_app() -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.include_router(chat_router)
    return app


@pytest.fixture
def client():
    limiter.reset()
    with TestClient(_chat_validation_app()) as c:
        yield c
    limiter.reset()


def test_chat_question_over_max_length_returns_422(client):
    payload = {
        "question": "x" * 2001,
        "doc_id": "doc-1",
        "match_count": 5,
    }
    with patch(
        "routes.chat.answer_question_for_document",
        new=AsyncMock(return_value={"answer": "ok", "chunks": 0}),
    ):
        resp = client.post("/chat", json=payload)
    assert resp.status_code == 422


def test_chat_match_count_zero_returns_422(client):
    payload = {"question": "q", "doc_id": "doc-1", "match_count": 0}
    with patch(
        "routes.chat.answer_question_for_document",
        new=AsyncMock(return_value={"answer": "ok", "chunks": 0}),
    ):
        resp = client.post("/chat", json=payload)
    assert resp.status_code == 422


def test_chat_match_count_over_max_returns_422(client):
    payload = {"question": "q", "doc_id": "doc-1", "match_count": 21}
    with patch(
        "routes.chat.answer_question_for_document",
        new=AsyncMock(return_value={"answer": "ok", "chunks": 0}),
    ):
        resp = client.post("/chat", json=payload)
    assert resp.status_code == 422


def test_chat_batch_over_max_queries_returns_422(client):
    queries = [{"question": "q", "doc_ids": ["d"]} for _ in range(21)]
    payload = {"queries": queries}
    with patch(
        "routes.chat.answer_questions_for_documents_batch",
        new=AsyncMock(return_value=[]),
    ):
        resp = client.post("/chat/batch", json=payload)
    assert resp.status_code == 422


def test_chat_doc_id_over_max_length_returns_422(client):
    payload = {
        "question": "q",
        "doc_id": "x" * 101,
        "match_count": 5,
    }
    with patch(
        "routes.chat.answer_question_for_document",
        new=AsyncMock(return_value={"answer": "ok", "chunks": 0}),
    ):
        resp = client.post("/chat", json=payload)
    assert resp.status_code == 422
