from core.auth import AuthContext
import pytest
from fastapi import HTTPException
from fastapi.responses import Response
from unittest.mock import AsyncMock, patch

from request_utils import make_test_request
from routes.documents import delete_document

@pytest.mark.asyncio
async def test_delete_document_success():
    payload = {
        "document_id": "doc-1",
        "status": "completed",
    }
    with patch("routes.documents.db.get_document_status", new=AsyncMock(return_value=payload)):
        with patch("routes.documents.ingestion_queue.queue_position", return_value=None):
            with patch("routes.documents.db.delete_document", new=AsyncMock()) as mock_delete:
                result = await delete_document(
                    make_test_request("DELETE", "/documents/doc-1"), "doc-1", auth=AuthContext()
                )
                
    assert isinstance(result, Response)
    assert result.status_code == 204
    mock_delete.assert_called_once_with("doc-1", tenant_id=None)
@pytest.mark.asyncio
async def test_delete_document_not_found():
    with patch("routes.documents.db.get_document_status", new=AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as excinfo:
            await delete_document(
                make_test_request("DELETE", "/documents/missing-doc"), "missing-doc", auth=AuthContext()
            )

    assert excinfo.value.status_code == 404
    assert excinfo.value.detail["code"] == "document_not_found"

@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["queued", "retrying", "extracting", "chunking", "embedding", "storing"])
async def test_delete_document_conflict(status):
    payload = {
        "document_id": "doc-1",
        "status": status,
    }
    with patch("routes.documents.db.get_document_status", new=AsyncMock(return_value=payload)):
        with pytest.raises(HTTPException) as excinfo:
            await delete_document(
                make_test_request("DELETE", "/documents/doc-1"), "doc-1", auth=AuthContext()
            )

    assert excinfo.value.status_code == 409
    assert excinfo.value.detail["code"] == "document_processing"

@pytest.mark.asyncio
async def test_delete_document_queue_conflict():
    payload = {
        "document_id": "doc-1",
        "status": "uploaded",
    }
    with patch("routes.documents.db.get_document_status", new=AsyncMock(return_value=payload)):
        with patch("routes.documents.ingestion_queue.queue_position", return_value=1):
            with pytest.raises(HTTPException) as excinfo:
                await delete_document(
                    make_test_request("DELETE", "/documents/doc-1"), "doc-1", auth=AuthContext()
                )

    assert excinfo.value.status_code == 409
    assert excinfo.value.detail["code"] == "document_queued"
