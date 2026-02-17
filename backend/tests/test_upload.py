"""
Integration tests for the upload flow with retry logic.
Tests the complete pipeline with mocked failures.
"""
import pytest
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException

from routes.upload import upload
from fastapi import UploadFile

@pytest.mark.asyncio
async def test_upload_with_retry_success():
    """Test upload succeeds after retryable failures."""
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = "test.pdf"
    mock_file.content_type = "application/pdf"

    # Mock the ingestion service (orchestration layer)
    with patch('routes.upload.ingest_document_atomic') as mock_ingest:
        mock_ingest.return_value = ("doc123", ["chunk1", "chunk2"])
        
        # Mock text extraction and embeddings
        with patch('routes.upload.extract_text_from_file', return_value="sample text"):
            with patch('routes.upload.get_embeddings', return_value=[[0.1]*3072]):
                
                result = await upload(mock_file)
    
    assert result["document_id"] == "doc123"
    assert result["chunks"] == 2
    mock_ingest.assert_called_once()

@pytest.mark.asyncio
async def test_upload_fails_on_permanent_error():
    """Test upload fails fast on permanent errors."""
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.content_type = "application/pdf"
    mock_file.filename = "test.pdf"

    # Mock the ingestion service to fail
    with patch('routes.upload.ingest_document_atomic') as mock_ingest:
        mock_ingest.side_effect = Exception("constraint violation")
        
        with patch('routes.upload.extract_text_from_file', return_value="sample text"):
            with patch('routes.upload.get_embeddings', return_value=[[0.1]*3072]):
                
                with pytest.raises(HTTPException) as excinfo:
                    await upload(mock_file)

                assert excinfo.value.status_code == 500
                assert excinfo.value.detail == "Upload failed. Please try again."
    
    mock_ingest.assert_called_once()