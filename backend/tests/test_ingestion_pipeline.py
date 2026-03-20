"""Ingestion pipeline tests for validation, status tracking, and failure handling."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import UploadFile

from services.ingestion_pipeline import IngestionPipeline, UploadPipelineError


class _FixedSplitter:
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split_text(self, text: str) -> list[str]:
        return ["chunk-a", "chunk-b"]


class _SingleChunkSplitter:
    def __init__(self, chunk_size: int, chunk_overlap: int):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split_text(self, text: str) -> list[str]:
        return ["chunk-a"]


@pytest.mark.asyncio
async def test_process_document_success_tracks_status_and_returns_status_endpoint(monkeypatch):
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = "test.pdf"
    mock_file.content_type = "application/pdf"
    mock_file.read = AsyncMock(return_value=b"fake-pdf-bytes")

    monkeypatch.setattr("services.ingestion_pipeline.config.MAX_UPLOAD_SIZE_BYTES", 10 * 1024 * 1024)
    monkeypatch.setattr("services.ingestion_pipeline.config.MAX_UPLOAD_SIZE_MB", 10)

    pipeline = IngestionPipeline(splitter_cls=_FixedSplitter)

    with patch("services.ingestion_pipeline.db.create_document", new=AsyncMock(return_value="doc123")) as mock_create, patch(
        "services.ingestion_pipeline.db.update_document_status", new=AsyncMock()
    ) as mock_update, patch(
        "services.ingestion_pipeline.db.store_chunks_with_embeddings", new=AsyncMock(return_value=["c1", "c2"])
    ) as mock_store, patch(
        "services.ingestion_pipeline.db.delete_document_chunks", new=AsyncMock()
    ) as mock_cleanup, patch(
        "services.ingestion_pipeline.extract_text_from_file", new=AsyncMock(return_value="hello world")
    ) as mock_extract, patch(
        "services.ingestion_pipeline.get_embeddings", new=AsyncMock(return_value=[[0.1, 0.2], [0.3, 0.4]])
    ):
        result = await pipeline.process_document(mock_file)

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
async def test_process_document_rejects_invalid_file_type():
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = "bad.docx"
    mock_file.content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    mock_file.read = AsyncMock(return_value=b"x")

    pipeline = IngestionPipeline(splitter_cls=_SingleChunkSplitter)

    with pytest.raises(UploadPipelineError) as excinfo:
        await pipeline.process_document(mock_file)

    assert excinfo.value.status_code == 400
    assert excinfo.value.code == "invalid_file_type"
    assert excinfo.value.stage == "validation"


@pytest.mark.asyncio
async def test_process_document_rejects_file_too_large(monkeypatch):
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = "large.pdf"
    mock_file.content_type = "application/pdf"
    mock_file.read = AsyncMock(return_value=b"x" * 20)

    monkeypatch.setattr("services.ingestion_pipeline.config.MAX_UPLOAD_SIZE_BYTES", 5)
    monkeypatch.setattr("services.ingestion_pipeline.config.MAX_UPLOAD_SIZE_MB", 0)

    pipeline = IngestionPipeline()

    with pytest.raises(UploadPipelineError) as excinfo:
        await pipeline.process_document(mock_file)

    assert excinfo.value.status_code == 413
    assert excinfo.value.code == "file_too_large"
    assert excinfo.value.stage == "validation"


@pytest.mark.asyncio
async def test_process_document_marks_failed_when_no_text_extracted(monkeypatch):
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = "empty.pdf"
    mock_file.content_type = "application/pdf"
    mock_file.read = AsyncMock(return_value=b"fake-pdf-bytes")

    monkeypatch.setattr("services.ingestion_pipeline.config.MAX_UPLOAD_SIZE_BYTES", 10 * 1024 * 1024)

    pipeline = IngestionPipeline()

    with patch("services.ingestion_pipeline.db.create_document", new=AsyncMock(return_value="doc-no-text")), patch(
        "services.ingestion_pipeline.db.update_document_status", new=AsyncMock()
    ) as mock_update, patch(
        "services.ingestion_pipeline.db.delete_document_chunks", new=AsyncMock()
    ) as mock_cleanup, patch(
        "services.ingestion_pipeline.extract_text_from_file", new=AsyncMock(return_value="   ")
    ):
        with pytest.raises(UploadPipelineError) as excinfo:
            await pipeline.process_document(mock_file)

    assert excinfo.value.status_code == 422
    assert excinfo.value.code == "no_text_extracted"
    assert excinfo.value.document_id == "doc-no-text"

    mock_cleanup.assert_awaited_once_with("doc-no-text")
    assert mock_update.await_args_list[-1].kwargs["status"] == "failed"
    assert mock_update.await_args_list[-1].kwargs["error"]["stage"] == "extracting"


@pytest.mark.asyncio
async def test_process_document_marks_failed_on_storage_error(monkeypatch):
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = "store-fail.pdf"
    mock_file.content_type = "application/pdf"
    mock_file.read = AsyncMock(return_value=b"fake-pdf-bytes")

    monkeypatch.setattr("services.ingestion_pipeline.config.MAX_UPLOAD_SIZE_BYTES", 10 * 1024 * 1024)

    pipeline = IngestionPipeline()

    with patch("services.ingestion_pipeline.db.create_document", new=AsyncMock(return_value="doc-store-fail")), patch(
        "services.ingestion_pipeline.db.update_document_status", new=AsyncMock()
    ) as mock_update, patch(
        "services.ingestion_pipeline.db.delete_document_chunks", new=AsyncMock()
    ) as mock_cleanup, patch(
        "services.ingestion_pipeline.extract_text_from_file", new=AsyncMock(return_value="hello world")), patch(
        "services.ingestion_pipeline.get_embeddings", new=AsyncMock(return_value=[[0.1, 0.2]])
    ), patch(
        "services.ingestion_pipeline.db.store_chunks_with_embeddings", new=AsyncMock(side_effect=RuntimeError("db down"))
    ):
        with pytest.raises(UploadPipelineError) as excinfo:
            await pipeline.process_document(mock_file)

    assert excinfo.value.status_code == 500
    assert excinfo.value.code == "upload_failed"
    assert excinfo.value.stage == "storing"
    assert excinfo.value.document_id == "doc-store-fail"

    mock_cleanup.assert_awaited_once_with("doc-store-fail")
    assert mock_update.await_args_list[-1].kwargs["status"] == "failed"
    assert mock_update.await_args_list[-1].kwargs["error"]["stage"] == "storing"
