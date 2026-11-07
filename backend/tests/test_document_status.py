import json
from types import SimpleNamespace

from core.auth import AuthContext, require_auth
import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

import main
from db.sqlalchemy_service import _document_status_payload
from middleware.rate_limit import limiter
from request_utils import make_test_request
from routes.documents import get_document_status, get_document_status_stream
from services.ingestion_job_metadata import build_document_status_response


def _safe_reset_limiter() -> None:
    try:
        limiter.reset()
    except Exception:
        pass


@pytest.fixture
def status_client():
    _safe_reset_limiter()
    main.app.dependency_overrides[require_auth] = lambda: AuthContext(tenant_id="dev")
    client = TestClient(main.app, raise_server_exceptions=False)
    try:
        yield client
    finally:
        main.app.dependency_overrides.pop(require_auth, None)
        _safe_reset_limiter()


@pytest.mark.asyncio
async def test_get_document_status_success():
    payload = {
        "document_id": "doc-1",
        "status": "embedding",
        "chunks": {"total": 10, "processed": 4},
        "error": None,
    }

    with patch("routes.documents.db.get_document_status", new=AsyncMock(return_value=payload)):
        result = await get_document_status(
            make_test_request("GET", "/documents/doc-1/status"), "doc-1", auth=AuthContext(tenant_id="dev")
        )

    assert result["document_id"] == "doc-1"
    assert result["status"] == "embedding"
    assert result["chunks"] == {"total": 10, "processed": 4}
    assert "error" not in result


@pytest.mark.asyncio
async def test_get_document_status_not_found():
    with patch("routes.documents.db.get_document_status", new=AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as excinfo:
            await get_document_status(
                make_test_request("GET", "/documents/missing-doc/status"),
                "missing-doc",
                auth=AuthContext(tenant_id="dev"),
            )

    assert excinfo.value.status_code == 404
    assert excinfo.value.detail["code"] == "document_not_found"
    assert excinfo.value.detail["document_id"] == "missing-doc"


def test_get_document_status_http_not_found_returns_404_json(status_client):
    unknown_id = "00000000-0000-0000-0000-000000000001"
    with patch("routes.documents.db.get_document_status", new=AsyncMock(return_value=None)) as mock_get:
        response = status_client.get(f"/documents/{unknown_id}/status")

    assert response.status_code == 404
    body = response.json()
    assert body == {
        "detail": {
            "code": "document_not_found",
            "message": "Document not found.",
            "document_id": unknown_id,
        }
    }
    assert isinstance(body["detail"]["document_id"], str)
    mock_get.assert_awaited_once_with(unknown_id, tenant_id="dev")


def test_get_document_status_http_found_returns_200(status_client):
    doc_id = "00000000-0000-0000-0000-000000000001"
    payload = {
        "document_id": doc_id,
        "status": "completed",
        "chunks": {"total": 3, "processed": 3},
        "error": None,
    }
    with patch("routes.documents.db.get_document_status", new=AsyncMock(return_value=payload)):
        response = status_client.get(f"/documents/{doc_id}/status")

    assert response.status_code == 200
    body = response.json()
    assert body["document_id"] == doc_id
    assert body["status"] == "completed"
    assert body["chunks"] == {"total": 3, "processed": 3}


def test_get_document_status_http_malformed_id_returns_422(status_client):
    with patch("routes.documents.db.get_document_status", new=AsyncMock(return_value=None)) as mock_get:
        response = status_client.get("/documents/not-a-uuid/status")

    assert response.status_code == 422
    body = response.json()
    assert body["detail"]["code"] == "validation_error"
    mock_get.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_document_status_stream_disabled():
    with patch("routes.documents.config") as mock_config:
        mock_config.ENABLE_STREAMING = False
        with pytest.raises(HTTPException) as excinfo:
            await get_document_status_stream(
                make_test_request("GET", "/documents/doc-1/status/stream"),
                "doc-1",
                auth=AuthContext(tenant_id="dev"),
            )
        assert excinfo.value.status_code == 400
        assert excinfo.value.detail["code"] == "streaming_disabled"


@pytest.mark.asyncio
async def test_get_document_status_stream_enabled_content_type():
    with patch("routes.documents.config") as mock_config:
        mock_config.ENABLE_STREAMING = True
        response = await get_document_status_stream(
            make_test_request("GET", "/documents/doc-1/status/stream"),
            "doc-1",
            auth=AuthContext(tenant_id="dev"),
        )
        assert isinstance(response, StreamingResponse)
        assert response.media_type == "text/event-stream"
        assert response.headers.get("Cache-Control") == "no-cache"
        assert response.headers.get("X-Accel-Buffering") == "no"


@pytest.mark.asyncio
async def test_get_document_status_stream_emits_status_and_closes_on_completed():
    payloads = [
        {"document_id": "doc-1", "status": "extracting", "chunks": None, "error": None},
        {"document_id": "doc-1", "status": "completed", "chunks": {"total": 5, "processed": 5}, "error": None},
    ]

    async def mock_get_document_status(doc_id, **kwargs):
        if payloads:
            return payloads.pop(0)
        return None

    request = make_test_request("GET", "/documents/doc-1/status/stream")
    request.is_disconnected = AsyncMock(return_value=False)

    with patch("routes.documents.config") as mock_config, \
         patch("routes.documents.db.get_document_status", new=AsyncMock(side_effect=mock_get_document_status)):
        mock_config.ENABLE_STREAMING = True
        response = await get_document_status_stream(request, "doc-1", auth=AuthContext(tenant_id="dev"))
        
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

        assert len(chunks) == 2
        
        assert chunks[0].startswith("event: status\ndata: ")
        data1 = json.loads(chunks[0].replace("event: status\ndata: ", "").strip())
        assert data1["status"] == "extracting"

        assert chunks[1].startswith("event: status\ndata: ")
        data2 = json.loads(chunks[1].replace("event: status\ndata: ", "").strip())
        assert data2["status"] == "completed"
        assert data2["chunks"]["total"] == 5


@pytest.mark.asyncio
async def test_status_stream_stays_open_while_retrying_and_closes_on_failure():
    payloads = [
        {"document_id": "doc-1", "status": "embedding", "chunks": None, "error": None},
        {"document_id": "doc-1", "status": "retrying", "chunks": None, "error": None},
        {
            "document_id": "doc-1",
            "status": "failed",
            "chunks": None,
            "error": {"code": "provider_timeout", "stage": "embedding", "message": "timed out"},
        },
    ]

    async def mock_get_document_status(doc_id, **kwargs):
        if payloads:
            return payloads.pop(0)
        return None

    request = make_test_request("GET", "/documents/doc-1/status/stream")
    request.is_disconnected = AsyncMock(return_value=False)

    with patch("routes.documents.config") as mock_config, \
         patch("routes.documents.db.get_document_status", new=AsyncMock(side_effect=mock_get_document_status)), \
         patch("routes.documents.asyncio.sleep", new=AsyncMock()):
        mock_config.ENABLE_STREAMING = True
        response = await get_document_status_stream(request, "doc-1", auth=AuthContext(tenant_id="dev"))

        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

    assert len(chunks) == 3
    statuses = [
        json.loads(chunk.replace("event: status\ndata: ", "").strip())["status"]
        for chunk in chunks
    ]
    assert statuses == ["embedding", "retrying", "failed"]


def test_document_status_payload_includes_stored_file_name():
    document = SimpleNamespace(
        id="doc-1",
        file_name="notes.txt",
        status="completed",
        status_detail=None,
        chunks={"total": 2, "processed": 2},
        error=None,
        doc_metadata={"source": "upload"},
        job_metadata={},
        created_at=None,
        updated_at=None,
    )

    payload = _document_status_payload(document)

    assert payload["file_name"] == "notes.txt"
    assert payload["document_id"] == "doc-1"
    assert payload["status"] == "completed"
    assert payload["chunks"] == {"total": 2, "processed": 2}
    assert payload["metadata"] == {"source": "upload"}
    assert payload["error"] is None


def test_status_response_includes_file_name_and_keeps_existing_fields():
    response = build_document_status_response(
        "doc-1",
        {
            "status": "completed",
            "chunks": {"total": 2, "processed": 2},
            "metadata": {"source": "upload"},
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:05Z",
            "file_name": "notes.txt",
            "error": None,
        },
    )

    assert response["file_name"] == "notes.txt"
    assert response["document_id"] == "doc-1"
    assert response["status"] == "completed"
    assert response["chunks"] == {"total": 2, "processed": 2}
    assert response["metadata"] == {"source": "upload"}
    assert response["created_at"] == "2026-01-01T00:00:00Z"
    assert "error" not in response


def test_status_response_without_file_name_keeps_other_fields():
    response = build_document_status_response(
        "doc-1",
        {
            "status": "embedding",
            "chunks": {"total": 4, "processed": 1},
            "metadata": {"source": "upload"},
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:05Z",
            "status_detail": "replacement_in_progress",
        },
    )

    assert "file_name" not in response
    assert response["document_id"] == "doc-1"
    assert response["status"] == "embedding"
    assert response["chunks"] == {"total": 4, "processed": 1}
    assert response["metadata"] == {"source": "upload"}
    assert response["status_detail"] == "replacement_in_progress"

    unset = build_document_status_response(
        "doc-1",
        {
            "status": "completed",
            "chunks": {"total": 1, "processed": 1},
            "metadata": {},
            "file_name": None,
        },
    )
    assert "file_name" not in unset
    assert unset["status"] == "completed"
    assert unset["chunks"] == {"total": 1, "processed": 1}


@pytest.mark.asyncio
async def test_get_document_status_includes_row_file_name():
    payload = {
        "document_id": "doc-1",
        "status": "completed",
        "chunks": {"total": 1, "processed": 1},
        "metadata": {},
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:05Z",
        "file_name": "notes.txt",
        "error": None,
    }

    with patch("routes.documents.db.get_document_status", new=AsyncMock(return_value=payload)):
        result = await get_document_status(
            make_test_request("GET", "/documents/doc-1/status"),
            "doc-1",
            auth=AuthContext(tenant_id="dev"),
        )

    assert result["file_name"] == "notes.txt"
    assert result["status"] == "completed"
    assert result["chunks"] == {"total": 1, "processed": 1}
    assert result["document_id"] == "doc-1"


@pytest.mark.asyncio
async def test_status_stream_includes_file_name_from_the_same_payload():
    payloads = [
        {
            "document_id": "doc-1",
            "status": "extracting",
            "chunks": None,
            "error": None,
            "file_name": "notes.txt",
        },
        {
            "document_id": "doc-1",
            "status": "completed",
            "chunks": {"total": 1, "processed": 1},
            "error": None,
            "file_name": "notes-v2.txt",
        },
    ]

    async def mock_get_document_status(doc_id, **kwargs):
        if payloads:
            return payloads.pop(0)
        return None

    request = make_test_request("GET", "/documents/doc-1/status/stream")
    request.is_disconnected = AsyncMock(return_value=False)

    with patch("routes.documents.config") as mock_config, \
         patch("routes.documents.db.get_document_status", new=AsyncMock(side_effect=mock_get_document_status)), \
         patch("routes.documents.asyncio.sleep", new=AsyncMock()):
        mock_config.ENABLE_STREAMING = True
        response = await get_document_status_stream(
            request, "doc-1", auth=AuthContext(tenant_id="dev")
        )

        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)

    assert len(chunks) == 2
    first = json.loads(chunks[0].replace("event: status\ndata: ", "").strip())
    second = json.loads(chunks[1].replace("event: status\ndata: ", "").strip())
    assert first["status"] == "extracting"
    assert first["file_name"] == "notes.txt"
    assert second["status"] == "completed"
    assert second["file_name"] == "notes-v2.txt"
    assert second["chunks"]["total"] == 1
