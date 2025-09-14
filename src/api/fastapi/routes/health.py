from fastapi import APIRouter
from src.utils.logging.otel_logger import logger

router = APIRouter()

@router.get("/health")
def health_check():
    logger.info("Health check endpoint hit")
    return {"status": "ok"}

@router.get("/ping")
def ping():
    logger.info("Ping endpoint hit")
    return {"status": "pong"}