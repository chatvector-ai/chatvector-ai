import os
import json
import pytest
from unittest import mock
from backend.core.config import config
from backend.services.embedding_service import get_embedding

@pytest.mark.asyncio
async def test_get_embedding_success(mocker):
    """
    Test that get_embedding returns a vector without hitting the external API.
    """
    # Define the mock return value (768 dimensions is standard for Gemini embedding-001)
    mock_embedding = {"embedding": [0.1] * 768}
    
    # Mock the genai.embed_content method
    mocker.patch(
        "google.generativeai.embed_content",
        return_value=mock_embedding
    )

    # Call the service
    text = "Test text for embedding"
    embedding = await get_embedding(text)
    
    # Assertions
    assert embedding == mock_embedding["embedding"]
    assert len(embedding) == 768



