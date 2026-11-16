"""Unit tests for the FastAPI proxy example's soft-error and status handling."""

from __future__ import annotations

import sys
from pathlib import Path
import pytest
import httpx

# Add the fastapi-proxy example to sys.path so app.main can be imported
PROXY_DIR = Path(__file__).resolve().parents[1] / "examples" / "fastapi-proxy"
if str(PROXY_DIR) not in sys.path:
    sys.path.insert(0, str(PROXY_DIR))

pytest.importorskip("fastapi")

from app.main import app, get_chatvector_client  # noqa: E402
from chatvector import AsyncChatVectorClient  # noqa: E402


@pytest.fixture(autouse=True)
def clean_dependency_overrides():
    """Ensure dependency overrides are restored after each test."""
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_proxy_chat_forwards_soft_error_status_and_error():
    """When ChatVector returns HTTP 200 with status='error', the proxy forwards status and error."""
    def mock_backend_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/sessions"):
            return httpx.Response(200, json={"id": "sess-test-1", "document_ids": []}, request=request)
        if request.url.path.endswith("/chat"):
            return httpx.Response(
                200,
                json={
                    "status": "error",
                    "question": "What is in this doc?",
                    "doc_id": "doc-test-1",
                    "chunks": 0,
                    "answer": "",
                    "error": {
                        "code": "anchor_document_excluded_by_filter",
                        "message": "The document was excluded by metadata filter",
                    },
                    "sources": [],
                    "session_id": "sess-test-1",
                },
                request=request,
            )
        return httpx.Response(404, request=request)

    mock_transport = httpx.MockTransport(mock_backend_handler)
    client = AsyncChatVectorClient(base_url="http://mock-cv")
    client._client = httpx.AsyncClient(base_url="http://mock-cv", transport=mock_transport)

    app.dependency_overrides[get_chatvector_client] = lambda: client

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        response = await ac.post(
            "/api/chat",
            headers={"x-user-id": "user-456"},
            json={
                "doc_id": "doc-test-1",
                "question": "What is in this doc?",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "sess-test-1"
    assert data["response"]["status"] == "error"
    assert data["response"]["error"] == {
        "code": "anchor_document_excluded_by_filter",
        "message": "The document was excluded by metadata filter",
    }
    assert data["response"]["answer"] == ""
    assert data["response"]["sources"] == []


@pytest.mark.asyncio
async def test_proxy_chat_success_includes_status_ok():
    """When ChatVector succeeds, the proxy forwards status='ok' and error=None."""
    def mock_backend_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/sessions"):
            return httpx.Response(200, json={"id": "sess-test-2", "document_ids": []}, request=request)
        if request.url.path.endswith("/chat"):
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "question": "Summarize this doc",
                    "doc_id": "doc-test-2",
                    "chunks": 2,
                    "answer": "This is a concise summary.",
                    "error": None,
                    "sources": [
                        {
                            "file_name": "guide.pdf",
                            "page_number": 1,
                            "chunk_index": 0,
                            "score": 0.95,
                            "score_type": "vector",
                        }
                    ],
                    "latency_ms": 120,
                    "model": "gemini-2.5-flash",
                    "session_id": "sess-test-2",
                },
                request=request,
            )
        return httpx.Response(404, request=request)

    mock_transport = httpx.MockTransport(mock_backend_handler)
    client = AsyncChatVectorClient(base_url="http://mock-cv")
    client._client = httpx.AsyncClient(base_url="http://mock-cv", transport=mock_transport)

    app.dependency_overrides[get_chatvector_client] = lambda: client

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        response = await ac.post(
            "/api/chat",
            headers={"x-user-id": "user-456"},
            json={
                "doc_id": "doc-test-2",
                "question": "Summarize this doc",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == "sess-test-2"
    assert data["response"]["status"] == "ok"
    assert data["response"]["error"] is None
    assert data["response"]["answer"] == "This is a concise summary."
    assert len(data["response"]["sources"]) == 1
    assert data["response"]["sources"][0]["file_name"] == "guide.pdf"
