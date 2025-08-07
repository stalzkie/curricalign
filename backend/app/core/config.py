import os
from dotenv import load_dotenv

load_dotenv()  # Load .env automatically

class Settings:
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")
    RETRAIN_MODELS: bool = os.getenv("RETRAIN_MODELS", "false").lower() == "true"
    SERPAPI_API_KEY: str = os.getenv("SERPAPI_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

settings = Settings()
