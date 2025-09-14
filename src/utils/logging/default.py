import logging

from src.utils.logging.otel_logger import get_logger


class Logger:
    """
    Basic logger that uses OpenTelemetry (OTEL) logger.

    This class wraps the OTEL logger and provides methods for different logging levels
    while maintaining request context information in the logs.

    Args:
        name (str): The name of the logger instance
        request_context (dict, optional): Dictionary containing request context information
    """

    def __init__(self, name: str, request_context: dict = None):
        self.base_logger: logging.Logger = get_logger(name)
        self.request_context = request_context

    def __add_request_context_to_extra(self, extra: dict) -> dict:
        """
        Merges the request context with additional extra information.

        Args:
            extra (dict): Additional context information to be added to the log

        Returns:
            dict: Merged dictionary of request context and extra information
        """
        if not extra:
            return self.request_context

        if not self.request_context:
            return extra

        extra = extra.copy()
        extra.update(self.request_context)
        return extra

    def debug(self, message, extra=None):
        """
        Log a message with DEBUG level.

        Args:
            message: The message to be logged
            extra (dict, optional): Additional context information for this log entry
        """
        self.base_logger.debug(
            message, extra=self.__add_request_context_to_extra(extra)
        )

    def info(self, message, extra=None):
        """
        Log a message with INFO level.

        Args:
            message: The message to be logged
            extra (dict, optional): Additional context information for this log entry
        """
        self.base_logger.info(message, extra=self.__add_request_context_to_extra(extra))

    def warning(self, message, extra=None):
        """
        Log a message with WARNING level.

        Args:
            message: The message to be logged
            extra (dict, optional): Additional context information for this log entry
        """
        self.base_logger.warning(
            message, extra=self.__add_request_context_to_extra(extra)
        )

    def error(self, message, extra=None):
        """
        Log a message with ERROR level.

        Args:
            message: The message to be logged
            extra (dict, optional): Additional context information for this log entry
        """
        self.base_logger.error(
            message, extra=self.__add_request_context_to_extra(extra)
        )

    def critical(self, message, extra=None):
        """
        Log a message with CRITICAL level.

        Args:
            message: The message to be logged
            extra (dict, optional): Additional context information for this log entry
        """
        self.base_logger.critical(
            message, extra=self.__add_request_context_to_extra(extra)
        )
