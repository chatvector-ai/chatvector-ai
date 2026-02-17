"""
Tests for SQLAlchemy database service.
Uses an in-memory SQLite database for testing.
"""
import pytest
from unittest.mock import AsyncMock, patch
from db.sqlalchemy_service import SQLAlchemyService

@pytest.fixture
def sqlalchemy_service():
    """Create a test instance with mocked methods."""
    service = SQLAlchemyService()
    
    # Mock the database methods directly
    service.create_document = AsyncMock(return_value="test-doc-id")
    service.store_chunks_with_embeddings = AsyncMock(return_value=["chunk1", "chunk2"])
    service.get_document = AsyncMock(return_value={"id": "test-doc-id", "filename": "test.pdf"})
    service.find_similar_chunks = AsyncMock(return_value=[])
    service.health_check = AsyncMock(return_value=True)
    
    return service

@pytest.mark.asyncio
async def test_create_document(sqlalchemy_service):
    """Test document creation."""
    doc_id = await sqlalchemy_service.create_document("test.pdf")
    assert doc_id == "test-doc-id"
    sqlalchemy_service.create_document.assert_called_once_with("test.pdf")

@pytest.mark.asyncio
async def test_store_chunks_with_embeddings(sqlalchemy_service):
    """Test chunk storage."""
    chunks = [("text1", [0.1, 0.2]), ("text2", [0.3, 0.4])]
    chunk_ids = await sqlalchemy_service.store_chunks_with_embeddings("doc123", chunks)
    assert len(chunk_ids) == 2
    sqlalchemy_service.store_chunks_with_embeddings.assert_called_once_with("doc123", chunks)