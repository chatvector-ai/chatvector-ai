from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, UploadFile

from core.auth import AuthContext
from request_utils import make_test_request
from routes.upload import upload
from services.ingestion_pipeline import UploadPipelineError


@pytest.mark.asyncio
async def test_upload_route_enqueues_job_and_returns_accepted():
    """Successful upload validates, creates a document, enqueues the job, and returns immediately."""
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = "test.pdf"
    mock_file.content_type = "application/pdf"
    mock_file.read = AsyncMock(return_value=b"fake-pdf-bytes")

    with (
        patch("routes.upload.ingestion_pipeline.validate_file", return_value=None),
        patch("routes.upload.db.create_document", new=AsyncMock(return_value="doc-1")),
        patch("routes.upload.db.update_document_status", new=AsyncMock()),
        patch("routes.upload.ingestion_queue.enqueue", new=AsyncMock(return_value=1)),
    ):
        result = await upload(make_test_request("POST", "/upload"), mock_file, auth=AuthContext())

    assert result["message"] == "Accepted"
    assert result["document_id"] == "doc-1"
    assert result["status"] == "queued"
    assert result["queue_position"] == 1
    assert result["status_endpoint"] == "/documents/doc-1/status"


@pytest.mark.asyncio
async def test_upload_route_maps_validation_error_to_http_exception():
    """A validation failure from the pipeline is surfaced as the correct HTTP error."""
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = "bad.docx"
    mock_file.content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    mock_file.read = AsyncMock(return_value=b"x")

    with patch(
        "routes.upload.ingestion_pipeline.validate_file",
        side_effect=UploadPipelineError(
            status_code=400,
            code="invalid_file_type",
            stage="validation",
            message="Only PDF and TXT files are supported.",
        ),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await upload(make_test_request("POST", "/upload"), mock_file, auth=AuthContext())

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "invalid_file_type"
    assert exc_info.value.detail["stage"] == "validation"
