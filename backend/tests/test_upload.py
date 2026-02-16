"""
Integration tests for the upload flow with retry logic.
Tests the complete pipeline with mocked failures.
"""
import pytest
from unittest.mock import AsyncMock, patch

from routes.upload import upload
from fastapi import UploadFile

@pytest.mark.asyncio
async def test_upload_with_retry_success():
    """Test upload succeeds after retryable failures."""
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = "test.pdf"
    
    # Mock the database calls with transient failures then success
    with patch('app.db.create_document') as mock_create:
        with patch('app.db.store_chunks_with_embeddings') as mock_store:
            # First call fails, second succeeds
            mock_create.side_effect = [
                Exception("connection timeout"),  # Transient
                "doc123"                          # Success
            ]
            mock_store.return_value = ["chunk1", "chunk2"]
            
            # Mock text extraction and embeddings
            with patch('app.routes.upload.extract_text_from_file', return_value="sample text"):
                with patch('app.routes.upload.get_embeddings', return_value=[[0.1]*384]):
                    
                    result = await upload(mock_file)
    
    assert result["document_id"] == "doc123"
    assert result["chunks"] == 2
    assert mock_create.call_count == 2  # One retry

@pytest.mark.asyncio
async def test_upload_fails_on_permanent_error():
    """Test upload fails fast on permanent errors."""
    mock_file = AsyncMock(spec=UploadFile)
    mock_file.filename = "test.pdf"
    
    with patch('app.db.create_document') as mock_create:
        # Permanent error
        mock_create.side_effect = Exception("constraint violation")
        
        with patch('app.routes.upload.extract_text_from_file', return_value="sample text"):
            with patch('app.routes.upload.get_embeddings', return_value=[[0.1]*384]):
                
                with pytest.raises(Exception, match="constraint violation"):
                    await upload(mock_file)
    
    assert mock_create.call_count == 1  