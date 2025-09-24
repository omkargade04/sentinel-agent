import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "sentinel-agent"
    
    env: str = os.getenv("ENV", "development")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "http://localhost:5432")
    try:
        SUPABASE_URL: str = os.getenv("SUPABASE_URL", "daa s")
        SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "asdas")
    except Exception as e:
        raise Exception(f"Error loading supabase credentials: {e}")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        
settings = Settings()