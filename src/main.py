import asyncio

import uvicorn
from dotenv import load_dotenv

from src.api.fastapi import FastAPIApp

load_dotenv()
app = FastAPIApp().get_app()


async def run_server():
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(run_server())
