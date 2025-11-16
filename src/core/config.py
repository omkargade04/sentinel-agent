import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "sentinel-agent"
    
    env: str = "development"
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/postgres"
    
    GITHUB_APP_ID: str = os.getenv("github_app_id", "1234567890")
    GITHUB_APP_PRIVATE_KEY: str = os.getenv("GITHUB_APP_PRIVATE_KEY", "1234567890")
    GITHUB_WEBHOOK_SECRET: str = os.getenv("GITHUB_WEBHOOK_SECRET", "1234567890")
    GITHUB_CLIENT_ID: str = os.getenv("GITHUB_CLIENT_ID", "")
    GITHUB_CLIENT_SECRET: str = os.getenv("GITHUB_CLIENT_SECRET", "")
    GITHUB_OAUTH_CLIENT_ID: str = os.getenv("GITHUB_OAUTH_CLIENT_ID", "")
    GITHUB_OAUTH_CLIENT_SECRET: str = os.getenv("GITHUB_OAUTH_CLIENT_SECRET", "")
    GITHUB_REDIRECT_URI: str = os.getenv("GITHUB_REDIRECT_URI", "http://localhost:8000/github/callback")
    GITHUB_APP_NAME: str = os.getenv("GITHUB_APP_NAME", "demo-sen-1")
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "https://<project_name>.supabase.co")
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "api_key")

    NGROK_AUTHTOKEN: str = os.getenv("NGROK_AUTHTOKEN", "1234567890")
    TEMPORAL_SERVER_URL: str = os.getenv("TEMPORAL_SERVER_URL", "localhost:7233")
    
    postgres_db: str = "postgres"
    postgres_user: str = "postgres" 
    posgtres_password: str = "postgres"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        
settings = Settings()