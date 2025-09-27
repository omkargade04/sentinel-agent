import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "sentinel-agent"
    
    env: str = "development"
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/postgres"
    
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "https://<project_name>.supabase.co")
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "api_key")

    postgres_db: str = "postgres"
    postgres_user: str = "postgres" 
    posgtres_password: str = "postgres"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        
settings = Settings()