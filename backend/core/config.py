import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    SUPABASE_URL: str = os.getenv("SUPABASE_URL")
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY")
    GEN_AI_KEY: str = os.getenv("GEN_AI_KEY")

# Create a single config object that other files can import
config = Settings()
