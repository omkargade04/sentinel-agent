from temporalio.client import Client
from src.core.config import settings
from src.utils.logging.otel_logger import logger

temporal_client: Client | None = None


async def init_temporal():
    """Initializes and connects the Temporal client."""
    global temporal_client
    try:
        temporal_client = await Client.connect(
            target_host=settings.TEMPORAL_SERVER_URL,
        )
        logger.info("Successfully connected to Temporal server.")
    except Exception as e:
        logger.error(f"Failed to connect to Temporal server: {e}")
        raise


async def disconnect_temporal():
    """Disconnects the Temporal client."""
    global temporal_client
    if temporal_client:
        await temporal_client.close()
        temporal_client = None
        logger.info("Successfully disconnected from Temporal server.")


def get_temporal_client() -> Client:
    """
    Returns the initialized Temporal client.

    This function can be used as a FastAPI dependency.
    """
    if not temporal_client:
        raise RuntimeError(
            "Temporal client has not been initialized. Ensure `init_temporal` is called at startup."
        )
    return temporal_client