from pathlib import Path
from dotenv import load_dotenv
import logging
import os
import sys

logger = logging.getLogger(__name__)

# Backend root is the expected location of .env
ROOT_DIR = Path(__file__).resolve().parent.parent  # core/ -> backend/
dotenv_path = ROOT_DIR / ".env"

if not dotenv_path.exists():
    logger.error(f".env file not found at expected location: {dotenv_path}")
    sys.exit(1)  # fail fast, so contributors know immediately

# Load environment variables from backend root/.env
load_dotenv(dotenv_path)
logger.debug(f"Loaded environment variables from {dotenv_path}")


class Settings:
    APP_ENV: str = os.getenv("APP_ENV", "production")
    IS_PROD = APP_ENV.lower() == "production"
    SUPABASE_URL: str = os.getenv("SUPABASE_URL")
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY")
    GEN_AI_KEY: str = os.getenv("GEN_AI_KEY")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
    LOG_USE_UTC: bool = os.getenv("LOG_USE_UTC", "false").lower() in ("1", "true", "yes")
    LOG_FORMAT: str = os.getenv("LOG_FORMAT", "TEXT").upper()  # Add this line - TEXT or JSON
    DATABASE_URL: str = os.getenv("DATABASE_URL")

    MAX_UPLOAD_SIZE_MB: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "10"))
    MAX_UPLOAD_SIZE_BYTES: int = MAX_UPLOAD_SIZE_MB * 1024 * 1024

    # Backwards-compatible lowercase properties for accessing config values
    @property
    def supabase_url(self) -> str:
        return self.SUPABASE_URL

    @property
    def supabase_key(self) -> str:
        return self.SUPABASE_KEY


config = Settings()
