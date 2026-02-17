import os
import sys
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
