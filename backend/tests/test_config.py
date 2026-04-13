import pytest
from core.config import get_embedding_dim

def test_get_embedding_dim_valid_int(monkeypatch):
    monkeypatch.setenv("EMBEDDING_DIM", "1536")
    assert get_embedding_dim() == 1536

def test_get_embedding_dim_invalid_value(monkeypatch):
    monkeypatch.setenv("EMBEDDING_DIM", "abc")
    with pytest.raises(ValueError) as exc:
        get_embedding_dim()
    
    assert "EMBEDDING_DIM='abc' is not a valid integer" in str(exc.value)
    assert "e.g. 3072 for Gemini" in str(exc.value)

def test_get_embedding_dim_missing_uses_provider(monkeypatch):
    monkeypatch.delenv("EMBEDDING_DIM", raising=False)
    # This should fall back to calling get_embedding_provider().embedding_dim
    # We mock it to avoid needing real provider setup
    from unittest.mock import patch
    with patch("services.providers.get_embedding_provider") as mock_get:
        mock_get.return_value.embedding_dim = 768
        assert get_embedding_dim() == 768
