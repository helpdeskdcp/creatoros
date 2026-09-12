"""Request-ID middleware: assigns/propagates X-Request-ID for log correlation."""
import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = structlog.get_logger("http")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        request.state.request_id = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)

        start = time.monotonic()
        try:
            response = await call_next(request)
        finally:
            duration_ms = round((time.monotonic() - start) * 1000, 2)
            structlog.contextvars.clear_contextvars()

        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response
