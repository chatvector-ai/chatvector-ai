import json
from core.auth import AuthContext
import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from unittest.mock import AsyncMock, patch

from request_utils import make_test_request
from routes.documents import get_document_status, get_document_status_stream


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
            make_test_request("GET", "/documents/doc-1/status"), "doc-1", auth=AuthContext()
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
                auth=AuthContext(),
            )

    assert excinfo.value.status_code == 404
    assert excinfo.value.detail["code"] == "document_not_found"
    assert excinfo.value.detail["document_id"] == "missing-doc"


@pytest.mark.asyncio
async def test_get_document_status_stream_disabled():
    with patch("routes.documents.config") as mock_config:
        mock_config.ENABLE_STREAMING = False
        with pytest.raises(HTTPException) as excinfo:
            await get_document_status_stream(
                make_test_request("GET", "/documents/doc-1/status/stream"),
                "doc-1",
                auth=AuthContext(),
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
            auth=AuthContext(),
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

    async def mock_get_document_status(doc_id):
        if payloads:
            return payloads.pop(0)
        return None

    request = make_test_request("GET", "/documents/doc-1/status/stream")
    request.is_disconnected = AsyncMock(return_value=False)

    with patch("routes.documents.config") as mock_config, \
         patch("routes.documents.db.get_document_status", new=AsyncMock(side_effect=mock_get_document_status)):
        mock_config.ENABLE_STREAMING = True
        response = await get_document_status_stream(request, "doc-1", auth=AuthContext())
        
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