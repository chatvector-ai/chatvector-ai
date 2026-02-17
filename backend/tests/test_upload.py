"""Upload route tests for validation, status tracking, and failure handling."""

import pytest
from fastapi import HTTPException, UploadFile
from unittest.mock import AsyncMock, patch

from routes.upload import upload


@pytest.mark.asyncio
async def test_upload_success_tracks_status_and_returns_status_endpoint(monkeypatch):
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = "test.pdf"
    mock_file.content_type = "application/pdf"
    mock_file.read = AsyncMock(return_value=b"fake-pdf-bytes")

    monkeypatch.setattr("routes.upload.config.MAX_UPLOAD_SIZE_BYTES", 10 * 1024 * 1024)
    monkeypatch.setattr("routes.upload.config.MAX_UPLOAD_SIZE_MB", 10)

    with patch("routes.upload.db.create_document", new=AsyncMock(return_value="doc123")) as mock_create, patch(
        "routes.upload.db.update_document_status", new=AsyncMock()
    ) as mock_update, patch(
        "routes.upload.db.store_chunks_with_embeddings", new=AsyncMock(return_value=["c1", "c2"])
    ) as mock_store, patch(
        "routes.upload.db.delete_document_chunks", new=AsyncMock()
    ) as mock_cleanup, patch(
        "routes.upload.extract_text_from_file", new=AsyncMock(return_value="hello world")
    ) as mock_extract, patch(
        "routes.upload.get_embeddings", new=AsyncMock(return_value=[[0.1, 0.2], [0.3, 0.4]])
    ):
        with patch("routes.upload.RecursiveCharacterTextSplitter") as mock_splitter_cls:
            mock_splitter = mock_splitter_cls.return_value
            mock_splitter.split_text.return_value = ["chunk-a", "chunk-b"]

            result = await upload(mock_file)

    assert result["document_id"] == "doc123"
    assert result["chunks"] == 2
    assert result["status"] == "completed"
    assert result["status_endpoint"] == "/documents/doc123/status"

    mock_create.assert_awaited_once()
    mock_extract.assert_awaited_once()
    mock_store.assert_awaited_once()
    mock_cleanup.assert_not_awaited()

    statuses = [call.kwargs.get("status") for call in mock_update.await_args_list]
    assert statuses == ["uploaded", "extracting", "chunking", "embedding", "storing", "completed"]


@pytest.mark.asyncio
async def test_upload_rejects_invalid_file_type():
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = "bad.docx"
    mock_file.content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    mock_file.read = AsyncMock(return_value=b"x")

    with pytest.raises(HTTPException) as excinfo:
        await upload(mock_file)

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail["code"] == "invalid_file_type"
    assert excinfo.value.detail["stage"] == "validation"


@pytest.mark.asyncio
async def test_upload_rejects_file_too_large(monkeypatch):
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = "large.pdf"
    mock_file.content_type = "application/pdf"
    mock_file.read = AsyncMock(return_value=b"x" * 20)

    monkeypatch.setattr("routes.upload.config.MAX_UPLOAD_SIZE_BYTES", 5)
    monkeypatch.setattr("routes.upload.config.MAX_UPLOAD_SIZE_MB", 0)

    with pytest.raises(HTTPException) as excinfo:
        await upload(mock_file)

    assert excinfo.value.status_code == 413
    assert excinfo.value.detail["code"] == "file_too_large"
    assert excinfo.value.detail["stage"] == "validation"


@pytest.mark.asyncio
async def test_upload_marks_failed_when_no_text_extracted(monkeypatch):
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = "empty.pdf"
    mock_file.content_type = "application/pdf"
    mock_file.read = AsyncMock(return_value=b"fake-pdf-bytes")

    monkeypatch.setattr("routes.upload.config.MAX_UPLOAD_SIZE_BYTES", 10 * 1024 * 1024)

    with patch("routes.upload.db.create_document", new=AsyncMock(return_value="doc-no-text")), patch(
        "routes.upload.db.update_document_status", new=AsyncMock()
    ) as mock_update, patch(
        "routes.upload.db.delete_document_chunks", new=AsyncMock()
    ) as mock_cleanup, patch(
        "routes.upload.extract_text_from_file", new=AsyncMock(return_value="   ")
    ):
        with pytest.raises(HTTPException) as excinfo:
            await upload(mock_file)

    assert excinfo.value.status_code == 422
    assert excinfo.value.detail["code"] == "no_text_extracted"
    assert excinfo.value.detail["document_id"] == "doc-no-text"

    mock_cleanup.assert_awaited_once_with("doc-no-text")
    assert mock_update.await_args_list[-1].kwargs["status"] == "failed"
    assert mock_update.await_args_list[-1].kwargs["failed_stage"] == "extracting"


@pytest.mark.asyncio
async def test_upload_marks_failed_on_storage_error(monkeypatch):
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = "store-fail.pdf"
    mock_file.content_type = "application/pdf"
    mock_file.read = AsyncMock(return_value=b"fake-pdf-bytes")

    monkeypatch.setattr("routes.upload.config.MAX_UPLOAD_SIZE_BYTES", 10 * 1024 * 1024)

    with patch("routes.upload.db.create_document", new=AsyncMock(return_value="doc-store-fail")), patch(
        "routes.upload.db.update_document_status", new=AsyncMock()
    ) as mock_update, patch(
        "routes.upload.db.delete_document_chunks", new=AsyncMock()
    ) as mock_cleanup, patch(
        "routes.upload.extract_text_from_file", new=AsyncMock(return_value="hello world")), patch(
        "routes.upload.get_embeddings", new=AsyncMock(return_value=[[0.1, 0.2]])
    ), patch(
        "routes.upload.db.store_chunks_with_embeddings", new=AsyncMock(side_effect=RuntimeError("db down"))
    ):
        with patch("routes.upload.RecursiveCharacterTextSplitter") as mock_splitter_cls:
            mock_splitter = mock_splitter_cls.return_value
            mock_splitter.split_text.return_value = ["chunk-a"]

            with pytest.raises(HTTPException) as excinfo:
                await upload(mock_file)

    assert excinfo.value.status_code == 500
    assert excinfo.value.detail["code"] == "upload_failed"
    assert excinfo.value.detail["stage"] == "storing"
    assert excinfo.value.detail["document_id"] == "doc-store-fail"

    mock_cleanup.assert_awaited_once_with("doc-store-fail")
    assert mock_update.await_args_list[-1].kwargs["status"] == "failed"
    assert mock_update.await_args_list[-1].kwargs["failed_stage"] == "storing"
