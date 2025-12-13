from logging import Logger
from fastapi import Request, status
from fastapi.responses import JSONResponse
import traceback

from src.models.schemas.responses import ErrorResponse


class AppException(Exception):
    """Base application exception."""
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(self.message)

class NotFoundException(AppException):
    """Raised when a resource is not found."""
    def __init__(self, message: str = "Resource not found"):
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, message=message)

class BadRequestException(AppException):
    """Raised for bad client requests."""
    def __init__(self, message: str = "Bad Request"):
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, message=message)

class DuplicateResourceException(AppException):
    """Raised when a resource already exists."""
    def __init__(self, message: str = "Resource already exists"):
        super().__init__(status_code=status.HTTP_409_CONFLICT, message=message)

class UnauthorizedException(AppException):
    """Raised for unauthorized access attempts."""
    def __init__(self, message: str = "Unauthorized"):
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, message=message)

class InstallationNotFoundError(NotFoundException):
    def __init__(self, message: str = "Installation not found"):
        super().__init__(message=message)

class RepositoryNotFoundError(NotFoundException):
    def __init__(self, message: str = "Repository not found"):
        super().__init__(message=message)

class UserNotFoundError(NotFoundException):
    def __init__(self, message: str = "User not found"):
        super().__init__(message=message)


class AppExceptionHandler:
    def __init__(self, logger: Logger):
        self.logger = logger

    async def handle_app_exception(self, request: Request, exc: AppException):
        self.logger.warning(f"Application error: {exc.message} for request {request.method} {request.url.path}")
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                errorMessage=exc.message
            ).model_dump(),
        )

    async def handle_generic_exception(self, request: Request, exc: Exception):
        self.logger.error(
            f"An unexpected error occurred: {exc} for request {request.method} {request.url.path}\n{traceback.format_exc()}"
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=ErrorResponse(
                errorMessage="An unexpected internal server error occurred."
            ).model_dump(),
        )

def add_exception_handlers(app, logger: Logger):
    handler = AppExceptionHandler(logger)
    app.add_exception_handler(AppException, handler.handle_app_exception)
    app.add_exception_handler(Exception, handler.handle_generic_exception)
    