import asyncio
from fastapi import FastAPI
import uvicorn
from dotenv import load_dotenv
from contextlib import asynccontextmanager

from src.api.fastapi import FastAPIApp
from src.utils.exception import add_exception_handlers
from src.core.temporal_client import TemporalClient
from src.core.neo4j import Neo4jConnection, get_neo4j_driver
from src.core.config import settings
from src.services.kg import init_database
from src.utils.logging.otel_logger import logger

load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up Sentinel AI Code Reviewer")
    
    # Initialize Temporal client
    try:
        temporal_client = TemporalClient()
        await temporal_client.connect()
        app.state.temporal_client = temporal_client
        logger.info("Successfully connected to Temporal server")
    except Exception as e:
        logger.error(f"Failed to connect to Temporal server: {e}")
        raise e
    
    # Initialize Neo4j database (constraints and indexes)
    try:
        neo4j_driver = get_neo4j_driver()
        await init_database(neo4j_driver, database=settings.NEO4J_DATABASE)
        logger.info(f"Successfully initialized Neo4j database: {settings.NEO4J_DATABASE}")
    except Exception as e:
        logger.error(f"Failed to initialize Neo4j database: {e}")
        raise e
    
    yield
    
    logger.info("Shutting down Sentinel AI Code Reviewer")
    
    # Close Temporal client
    try:
        if hasattr(app.state, "temporal_client"):
            await app.state.temporal_client.close()
            logger.info("Successfully disconnected from Temporal server")
    except Exception as e:
        logger.error(f"Failed to disconnect from Temporal server: {e}")
    
    # Close Neo4j driver
    try:
        await Neo4jConnection.close_driver()
        logger.info("Successfully closed Neo4j driver")
    except Exception as e:
        logger.error(f"Failed to close Neo4j driver: {e}")

app_instance = FastAPIApp(lifespan=lifespan)
app = app_instance.get_app()

add_exception_handlers(app, logger)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
