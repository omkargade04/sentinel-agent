from logging import Logger
from fastapi import status
from fastapi.responses import JSONResponse
import traceback

from src.models.schemas.responses import ErrorResponse

class ExceptionHandler:
    def __init__(self, logger: Logger):
        self.logger = logger

    def handle_exception(self, e: Exception, request_id: str) -> JSONResponse:
            if isinstance(e, ValueError):
                self.logger.error(f"Value error: {str(e)}", {"request_id": request_id})
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content=ErrorResponse(
                        success=False, errorMessage=f"validation error: {e}"
                    ).model_dump(),
                )
            else:
                tb_str = traceback.format_exc()
                self.logger.error(
                    f"Internal error - Type: {type(e).__name__}, Message: {str(e)}\nTraceback:\n{tb_str}", 
                    {"request_id": request_id}
                )
                return JSONResponse(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    content=ErrorResponse(
                        success=False, errorMessage=f"an internal error just occurred"
                    ).model_dump(),
                )