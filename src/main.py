import asyncio

import uvicorn
from dotenv import load_dotenv

from src.api.fastapi import FastAPIApp
from src.utils.exception import add_exception_handlers
from src.utils.logging.otel_logger import logger

load_dotenv()
app = FastAPIApp().get_app()

add_exception_handlers(app, logger)

async def run_server():
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(run_server())
