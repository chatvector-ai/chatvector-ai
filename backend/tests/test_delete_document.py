import pytest
from fastapi import HTTPException
from fastapi.responses import Response
from unittest.mock import AsyncMock, patch

from routes.documents import delete_document

@pytest.mark.asyncio
async def test_delete_document_success():
    payload = {
        "document_id": "doc-1",
        "status": "completed",
    }
    with patch("routes.documents.db.get_document_status", new=AsyncMock(return_value=payload)):
        with patch("routes.documents.db.delete_document", new=AsyncMock()) as mock_delete:
            result = await delete_document("doc-1")
            
    assert isinstance(result, Response)
    assert result.status_code == 204
    mock_delete.assert_called_once_with("doc-1")

@pytest.mark.asyncio
async def test_delete_document_not_found():
    with patch("routes.documents.db.get_document_status", new=AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as excinfo:
            await delete_document("missing-doc")

    assert excinfo.value.status_code == 404
    assert excinfo.value.detail["code"] == "document_not_found"

@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["queued", "extracting", "embedding"])
async def test_delete_document_conflict(status):
    payload = {
        "document_id": "doc-1",
        "status": status,
    }
    with patch("routes.documents.db.get_document_status", new=AsyncMock(return_value=payload)):
        with pytest.raises(HTTPException) as excinfo:
            await delete_document("doc-1")

    assert excinfo.value.status_code == 409
    assert excinfo.value.detail["code"] == "document_processing"
