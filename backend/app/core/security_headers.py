"""Security-response-headers middleware. CreatorOS previously shipped with
only CORS configured -- no CSP/HSTS/X-Frame-Options/etc at all (confirmed
absent in the production audit). This adds the standard defensive set to
every response."""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, hsts_enabled: bool) -> None:
        super().__init__(app)
        self._hsts_enabled = hsts_enabled

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # This is an API -- it never serves HTML for third-party embedding,
        # so a strict default-src 'none' is correct (docs/redoc pages are
        # the one exception and set their own permissive CSP via FastAPI).
        if not request.url.path.startswith(("/docs", "/redoc")):
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        if self._hsts_enabled:
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response
