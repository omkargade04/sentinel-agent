import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from src.utils.logging import Logger


class LogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        LOGGER = Logger("FastAPIApp")

        request_id = str(uuid.uuid4())
        request.state.id = request_id

        # Skip logging for health endpoint
        if (
            request.url.path == "/health"
            or request.url.path == "/"
            or request.url.path == "/metrics"
        ):
            return await call_next(request)

        # Create a copy of the request body to avoid consuming it
        request_body = await request.body()
        client = request.headers.get("x-sentinel", None)

        # Log Request Details
        extra = {
            "method": request.method,
            "url": str(request.url),
            "request_id": request.state.id,
            "client": client if client else "unknown",
            "ip": request.client.host,
        }

        LOGGER.info("Incoming Request", extra)

        # Clone the request to preserve the original body
        request.scope["_body"] = request_body

        try:
            # Call the next middleware or endpoint
            response = await call_next(request)
        except Exception as e:
            extra.update(
                {
                    "error": str(e),
                }
            )

            LOGGER.error("Error in request processing", extra=extra)
            raise

        extra.update(
            {
                "status_code": response.status_code,
            }
        )

        LOGGER.info("Response", extra=extra)

        return response
