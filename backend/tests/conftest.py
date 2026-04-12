import os
import sys
import pytest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Ensure imports relying on backend/.env do not crash test collection.
os.environ.setdefault("APP_ENV", "production")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key-123")
os.environ.setdefault("GEN_AI_KEY", "test-genai-key")
os.environ.setdefault("LOG_LEVEL", "DEBUG")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/postgres",
)

env_file = BACKEND_DIR / ".env"
if not env_file.exists():
    env_file.write_text(
        "\n".join(
            [
                "APP_ENV=production",
                "SUPABASE_URL=https://test.supabase.co",
                "SUPABASE_KEY=test-key-123",
                "GEN_AI_KEY=test-genai-key",
                "LOG_LEVEL=DEBUG",
                "DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/postgres",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


@pytest.fixture(scope="session", autouse=True)
def clear_test_logs():
    """Clear test log files at the start of each test session.

    Prevents test output from accumulating across runs and keeps the
    test log stream readable. Only clears logs/test.log and
    logs/test_access.log — production log files are never touched.
    """
    logs_dir = BACKEND_DIR / "logs"
    test_log_files = [
        logs_dir / "test.log",
        logs_dir / "test_access.log",
    ]
    for log_file in test_log_files:
        if log_file.exists():
            log_file.write_text("", encoding="utf-8")
    yield
