from supabase import create_client
from backend.core.config import config

supabase_client = create_client(
    config.SUPABASE_URL,
    config.SUPABASE_KEY
)
