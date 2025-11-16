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

# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     temporal_client = TemporalClient()
#     try:
#         await temporal_client.connect()
#     except Exception as e:
#         logger.error(f"Failed to connect to Temporal server: {e}")
#         raise e
#     logger.info("Starting up Sentinel AI Code Reviewer")
#     yield
#     logger.info("Shutting down Sentinel AI Code Reviewer")
#     try:
#         await temporal_client.disconnect()
#     except Exception as e:
#         logger.error(f"Failed to disconnect from Temporal server: {e}")
#         raise e

app = FastAPIApp().get_app()

add_exception_handlers(app, logger)

async def run_server():
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)
    temporal_client = TemporalClient()
    try:
        await temporal_client.connect()
        await server.serve()
    except Exception as e:
        logger.error(f"Failed to serve: {e}")
        raise e
    finally:
        await temporal_client.disconnect()

if __name__ == "__main__":
    asyncio.run(run_server())
