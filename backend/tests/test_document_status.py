import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, patch

from routes.documents import get_document_status


@pytest.mark.asyncio
async def test_get_document_status_success():
    payload = {
        "document_id": "doc-1",
        "status": "embedding",
        "chunks_total": 10,
        "chunks_processed": 4,
    }

    with patch("routes.documents.db.get_document_status", new=AsyncMock(return_value=payload)):
        result = await get_document_status("doc-1")

    assert result["document_id"] == "doc-1"
    assert result["status"] == "embedding"


@pytest.mark.asyncio
async def test_get_document_status_not_found():
    with patch("routes.documents.db.get_document_status", new=AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as excinfo:
            await get_document_status("missing-doc")

    assert excinfo.value.status_code == 404
    assert excinfo.value.detail["code"] == "document_not_found"
    assert excinfo.value.detail["document_id"] == "missing-doc"
