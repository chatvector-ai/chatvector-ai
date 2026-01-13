from supabase import create_client
from backend.core.config import config
from backend.core.logging_config import setup_logging
import logging

setup_logging()
logger = logging.getLogger(__name__)

class _LazySupabaseClient:
    """Lazy-initializing supabase client proxy.

    Accessing any attribute will create the real client using values from
    `backend/core/.env` or environment variables. This avoids creating the
    client at import time (which causes the app to crash if creds are missing).
    """
    def __init__(self):
        self._client = None

    def _ensure_client(self):
        if self._client is None:
            if not config.SUPABASE_URL or not config.SUPABASE_KEY:
                raise RuntimeError(
                    "Supabase credentials are not set. Set SUPABASE_URL and SUPABASE_KEY in backend/core/.env or environment variables."
                )
            self._client = create_client(
                config.SUPABASE_URL,
                config.SUPABASE_KEY
            )
            logger.info("Supabase client initialized successfully.")

    def __getattr__(self, name):
        self._ensure_client()
        return getattr(self._client, name)


# Export an object with the same name as before for backwards compatibility
supabase_client = _LazySupabaseClient()