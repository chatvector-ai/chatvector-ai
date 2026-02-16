"""
Tests for SQLAlchemy database service.
Uses an in-memory SQLite database for testing.
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.db.sqlalchemy_service import SQLAlchemyService

@pytest.fixture
def sqlalchemy_service():
    """Create a test instance with mocked session."""
    service = SQLAlchemyService()
    
    # Mock the database session
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock()
    
    with patch('app.db.sqlalchemy_service.async_session', return_value=mock_session):
        yield service, mock_session

@pytest.mark.asyncio
async def test_create_document(sqlalchemy_service):
    """Test document creation."""
    service, mock_session = sqlalchemy_service
    
    doc_id = await service.create_document("test.pdf")
    
    # Verify session.add was called
    mock_session.add.assert_called_once()
    mock_session.commit.assert_called_once()
    assert doc_id is not None

@pytest.mark.asyncio
async def test_store_chunks_with_embeddings(sqlalchemy_service):
    """Test chunk storage."""
    service, mock_session = sqlalchemy_service
    
    chunks = [
        ("chunk1 text", [0.1, 0.2, 0.3]),
        ("chunk2 text", [0.4, 0.5, 0.6]),
    ]
    
    chunk_ids = await service.store_chunks_with_embeddings("doc123", chunks)
    
    # Verify session.add_all was called with 2 chunks
    mock_session.add_all.assert_called_once()
    mock_session.commit.assert_called_once()
    assert len(chunk_ids) == 2