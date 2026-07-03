"""Integration tests for per-IP API rate limiting (slowapi).

Uses a minimal FastAPI app (upload + chat routers only) so tests do not import
``main`` and trigger DB driver / lifespan side effects at collection time.
"""

from io import BytesIO
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from middleware.rate_limit import limiter
from routes.chat import router as chat_router
from routes.upload import router as upload_router


async def _rate_limit_exceeded_handler(
    _request: Request, _exc: RateLimitExceeded
) -> JSONResponse:
    """Mirrors ``main.rate_limit_exceeded_handler`` (tests avoid importing ``main``)."""
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

# Burst sizes match default Settings when env does not override rate limits.
_UPLOAD_WINDOW = 20
_CHAT_WINDOW = 30

# Valid document ID for POST /chat (Pydantic UUID validation).
_CHAT_DOC_ID = "00000000-0000-0000-0000-000000000001"


def _rate_limited_test_app() -> FastAPI:
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.include_router(upload_router)
    app.include_router(chat_router)
    return app


@pytest.fixture(autouse=True)
def reset_rate_limit_storage():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def client():
    with TestClient(_rate_limited_test_app()) as c:
        yield c


def test_post_upload_returns_429_after_limit_exceeded(client):
    files = {"file": ("t.pdf", BytesIO(b"%PDF-1.4"), "application/pdf")}
    with (
        patch("routes.upload.ingestion_pipeline.validate_file", return_value=None),
        patch("routes.upload.db.create_document", new=AsyncMock(return_value="doc-rl")),
        patch("routes.upload.db.update_document_status", new=AsyncMock()),
        patch("routes.upload.ingestion_queue.enqueue", new=AsyncMock(return_value=1)),
    ):
        for _ in range(_UPLOAD_WINDOW):
            assert client.post("/upload", files=files).status_code == 202
        limited = client.post("/upload", files=files)
    assert limited.status_code == 429


def test_post_chat_returns_429_after_limit_exceeded(client):
    payload = {"question": "hello", "doc_id": _CHAT_DOC_ID, "match_count": 5}
    with (
        patch("routes.chat.answer_question_for_document", new=AsyncMock(return_value={"answer": "ok", "chunks": 0})),
        patch("routes.chat.db.get_document", new=AsyncMock(return_value={"id": _CHAT_DOC_ID})),
    ):
        for _ in range(_CHAT_WINDOW):
            assert client.post("/chat", json=payload).status_code == 200
        limited = client.post("/chat", json=payload)
    assert limited.status_code == 429


def test_429_response_has_standard_error_shape(client):
    files = {"file": ("x.pdf", BytesIO(b"%PDF-1.4"), "application/pdf")}
    with (
        patch("routes.upload.ingestion_pipeline.validate_file", return_value=None),
        patch("routes.upload.db.create_document", new=AsyncMock(return_value="doc-x")),
        patch("routes.upload.db.update_document_status", new=AsyncMock()),
        patch("routes.upload.ingestion_queue.enqueue", new=AsyncMock(return_value=1)),
    ):
        for _ in range(_UPLOAD_WINDOW):
            client.post("/upload", files=files)
        resp = client.post("/upload", files=files)
    assert resp.status_code == 429
    body = resp.json()
    assert body["detail"]["code"] == "rate_limited"
    assert "message" in body["detail"]


def test_429_includes_retry_after_header(client):
    payload = {"question": "q", "doc_id": _CHAT_DOC_ID, "match_count": 5}
    with (
        patch("routes.chat.answer_question_for_document", new=AsyncMock(return_value={"answer": "a", "chunks": 0})),
        patch("routes.chat.db.get_document", new=AsyncMock(return_value={"id": _CHAT_DOC_ID})),
    ):
        for _ in range(_CHAT_WINDOW):
            client.post("/chat", json=payload)
        resp = client.post("/chat", json=payload)
    assert resp.status_code == 429
    assert resp.headers.get("Retry-After") == "60"
