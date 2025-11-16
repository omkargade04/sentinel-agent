from temporalio.client import Client
from src.core.config import settings
from src.utils.logging.otel_logger import logger

class TemporalClient:
    def __init__(self):
        self.client = None

    async def connect(self):
        self.client = await Client.connect("localhost:7233")
        logger.info(f"Successfully connected to Temporal server at localhost:7233")

    async def disconnect(self):
        await self.client.close()
        self.client = None
        logger.info("Successfully disconnected from Temporal server.")
        
    async def get_client(self):
        if not self.client:
            await self.connect()
        return self.client
    
temporal_client = TemporalClient()