"""Tests for GET /documents."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from core.auth import AuthContext
from routes.documents import list_documents
from request_utils import make_test_request


@pytest.mark.asyncio
async def test_list_documents_returns_tenant_scoped_summaries():
    summaries = [
        {
            "document_id": "doc-1",
            "file_name": "japan.txt",
            "status": "completed",
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:01:00",
        }
    ]

    with patch(
        "routes.documents.db.list_tenant_document_summaries",
        new=AsyncMock(return_value=summaries),
    ) as mock_list:
        response = await list_documents(
            make_test_request("GET", "/documents"),
            auth=AuthContext(tenant_id="dev"),
        )

    mock_list.assert_awaited_once_with("dev")
    assert response == {"tenant_id": "dev", "documents": summaries}


@pytest.mark.asyncio
async def test_list_documents_requires_auth_tenant_context():
    with patch(
        "routes.documents.db.list_tenant_document_summaries",
        new=AsyncMock(return_value=[]),
    ):
        with pytest.raises(HTTPException) as exc:
            await list_documents(
                make_test_request("GET", "/documents"),
                auth=AuthContext(tenant_id=None),
            )

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_list_tenant_document_summaries_includes_error_from_row():
    from db.sqlalchemy_service import SQLAlchemyService
    from unittest.mock import MagicMock

    document = MagicMock()
    document.id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    document.file_name = "broken.pdf"
    document.status = "failed"
    document.doc_metadata = {}
    document.status_detail = None
    document.error = {"stage": "embedding", "message": "boom"}
    document.created_at = None
    document.updated_at = None

    class _ScalarResult:
        def scalars(self):
            return self

        def all(self):
            return [document]

    class _Session:
        async def execute(self, _stmt):
            return _ScalarResult()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    svc = SQLAlchemyService.__new__(SQLAlchemyService)
    svc.async_session = lambda: _Session()

    summaries = await svc.list_tenant_document_summaries("tenant-a")
    assert summaries == [
        {
            "document_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "file_name": "broken.pdf",
            "status": "failed",
            "metadata": {},
            "created_at": None,
            "updated_at": None,
            "error": {"stage": "embedding", "message": "boom"},
        }
    ]
