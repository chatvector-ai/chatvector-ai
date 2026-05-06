from core.auth import AuthContext
import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, patch

from request_utils import make_test_request
from routes.documents import get_document_status


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
