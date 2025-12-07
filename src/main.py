import asyncio
from fastapi import FastAPI
import uvicorn
from dotenv import load_dotenv
from contextlib import asynccontextmanager

from src.api.fastapi import FastAPIApp
from src.utils.exception import add_exception_handlers
from src.core.temporal_client import TemporalClient
from src.utils.logging.otel_logger import logger

load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up Sentinel AI Code Reviewer")
    try:
        temporal_client = TemporalClient()
        await temporal_client.connect()
    except Exception as e:
        logger.error(f"Failed to connect to Temporal server: {e}")
        raise e
    
    yield
    
    logger.info("Shutting down Sentinel AI Code Reviewer")
    try:
        await app.state.temporal_client.close()
        logger.info("Successfully disconnected from Temporal server")
    except Exception as e:
        logger.error(f"Failed to disconnect from Temporal server: {e}")

app_instance = FastAPIApp(lifespan=lifespan)
app = app_instance.get_app()

add_exception_handlers(app, logger)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
