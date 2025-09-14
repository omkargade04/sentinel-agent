import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "sentinel-agent"
    
    env: str = os.getenv("ENV", "development")
    database_url: str = os.getenv("DATABASE_URL", "http://localhost:5432")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        
settings = Settings()