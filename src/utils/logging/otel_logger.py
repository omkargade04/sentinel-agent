import logging
import os

from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs._internal.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from pythonjsonlogger import jsonlogger

SERVICE_NAME: str = "sentinel-agent"
SERVICE_VERSION: str = "1.0.0"

BASE_LOGGER_CACHE = {}


def get_logger(name: str) -> logging.Logger:
    """
    Returns the logger with the given name is exists, else creates a new one.
    """
    if name in BASE_LOGGER_CACHE:
        return BASE_LOGGER_CACHE[name]

    # Initialize the base logger
    base_logger = logging.getLogger(name)
    base_logger.setLevel(logging.DEBUG)
    BASE_LOGGER_CACHE[name] = base_logger

    # Add stream handler with JSON formatting
    stream_handler = logging.StreamHandler()

    base_logger.addHandler(stream_handler)
    base_logger.debug(f"Logger '{name}' initialized successfully")

    # Add OTEL handler
    try:
        if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", False):
            logger_provider = LoggerProvider(
                Resource.create(
                    {
                        "service.name": SERVICE_NAME,
                        "service.version": SERVICE_VERSION,
                        "host.name": os.getenv("DOMAIN_NAME", "ENV_NOT_SET"),
                    }
                )
            )
            exporter = OTLPLogExporter(
                endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"), insecure=True
            )
            logger_provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
            handler = LoggingHandler(
                level=logging.DEBUG, logger_provider=logger_provider
            )
            base_logger.addHandler(handler)
            base_logger.info(
                f"Successfully configured OTEL handler for the logger '{name}'"
            )
    except Exception as e:
        base_logger.error(e)

    return base_logger

logger = get_logger("sentinel-agent")
