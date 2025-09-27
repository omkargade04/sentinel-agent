from fastapi import HTTPException, status
from supabase import Client, create_client
import logging
from src.utils.logging.otel_logger import logger
from src.core.config import settings

def get_supabase_client() -> Client:
    """
    Dependency function to create and return a Supabase client.
    """
    if not settings.SUPABASE_URL or not settings.SUPABASE_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Supabase client is not configured on the server."
        )
    try:
        client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
        return client
    except Exception as e:
        logging.error(f"Failed to create Supabase client: {e}")
        raise e
