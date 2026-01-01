import pytest
from backend.services.embedding_service import get_embedding

@pytest.mark.asyncio
async def test_get_embedding_success(mocker):
    """
    Test that get_embedding returns a vector without hitting the external API.
    """
    # 1. Define the mock return value (768 dimensions is standard for Gemini embedding-001)
    mock_embedding = {"embedding": [0.1] * 768}
    
    # 2. Mock the genai.embed_content method
    mocker.patch(
        "google.generativeai.embed_content",
        return_value=mock_embedding
    )
    
    # 3. Call the service
    text = "Test text for embedding"
    embedding = await get_embedding(text)
    
    # 4. Assertions
    assert embedding == mock_embedding["embedding"]
    assert len(embedding) == 768
    
# --- The fix is below (added '@') ---
@pytest.mark.asyncio
async def test_get_embedding_retry_failure(mocker):
    """
    Test that the service retries 3 times on failure and returns a zero vector.
    """
    # Make the API raise an exception every time it is called
    mock_genai = mocker.patch("google.generativeai.embed_content")
    mock_genai.side_effect = Exception("API Unavailable")

    # Mock asyncio.sleep so the test runs instantly instead of waiting
    mocker.patch("asyncio.sleep")

    # Call the service
    result = await get_embedding("fail text")

    # Assertions
    assert len(result) == 768
    assert result == [0.0] * 768  # return zero vector
    assert mock_genai.call_count == 3  # tried 3 times