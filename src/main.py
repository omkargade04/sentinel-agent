import asyncio
from fastapi import FastAPI
import uvicorn
from dotenv import load_dotenv
from contextlib import asynccontextmanager

from src.api.fastapi import FastAPIApp
from src.utils.exception import add_exception_handlers
from src.core.temporal_client import init_temporal, disconnect_temporal
from src.utils.logging.otel_logger import logger

load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up Sentinel AI Code Reviewer")
    await init_temporal()
    yield
    logger.info("Shutting down Sentinel AI Code Reviewer")
    await disconnect_temporal()

app = FastAPIApp(lifespan=lifespan).get_app()

add_exception_handlers(app, logger)

async def run_server():
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(run_server())
