"""Consistent application error type and FastAPI exception handlers.

Every error response has the same shape:
    {"error": {"code": "...", "message": "...", "request_id": "..."}}
so frontend error handling never has to special-case an endpoint.
"""
from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int = status.HTTP_400_BAD_REQUEST):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class NotFoundError(AppError):
    def __init__(self, message: str = "Resource not found"):
        super().__init__("not_found", message, status.HTTP_404_NOT_FOUND)


class ConflictError(AppError):
    def __init__(self, message: str = "Resource already exists"):
        super().__init__("conflict", message, status.HTTP_409_CONFLICT)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Authentication required"):
        super().__init__("unauthorized", message, status.HTTP_401_UNAUTHORIZED)


class ForbiddenError(AppError):
    def __init__(self, message: str = "Insufficient permissions"):
        super().__init__("forbidden", message, status.HTTP_403_FORBIDDEN)


class ValidationError(AppError):
    def __init__(self, message: str = "Invalid input"):
        super().__init__("invalid_input", message, status.HTTP_400_BAD_REQUEST)


def _envelope(request: Request, code: str, message: str) -> dict:
    request_id = getattr(request.state, "request_id", None)
    return {"error": {"code": code, "message": message, "request_id": request_id}}


def register_exception_handlers(app) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(request, exc.code, exc.message),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(request, "http_error", str(exc.detail)),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_envelope(request, "validation_error", "Invalid request payload")
            | {"details": exc.errors()},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope(request, "internal_error", "An unexpected error occurred"),
        )
