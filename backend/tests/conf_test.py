import os
import pytest
from unittest import mock

#Set fake env vars BEFORE any logic runs or modules are imported
os.environ["SUPABASE_URL"] = "https://test.supabase.co"
os.environ["SUPABASE_KEY"] = "test-key-123"
os.environ["GEN_AI_KEY"] = "test-genai-key"
os.environ["LOG_LEVEL"] = "DEBUG"

@pytest.fixture(scope="session", autouse=True)
def mock_settings():
    """
    (Optional) Helper if you need to enforce specific settings later.
    The os.environ lines above do the heavy lifting for import-time config.
    """
    yield



    "   # Now import the modules that rely on these env vars"
    from core.config import config

    assert config.SUPABASE_URL == "https://test.supabase.co"
    assert config.SUPABASE_KEY == "test-key-123"
    assert config.GEN_AI_KEY == "test-genai-key"
    assert config.LOG_LEVEL == "DEBUG"
    yield

