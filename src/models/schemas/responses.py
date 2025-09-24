from pydantic import BaseModel


class BaseResponse(BaseModel):
    """Base response model for all API responses"""

    success: bool


class ErrorResponse(BaseModel):
    """Error response model for 400 and 5xx responses"""

    success: bool = False
    errorMessage: str
