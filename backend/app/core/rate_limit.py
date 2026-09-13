"""Application-level rate limiting. The production audit confirmed there
was none at all -- YouTube-provider retry/backoff only reacts *after* a
429, nothing throttled outbound OR inbound traffic proactively.

Fixed-window counter backed by Redis (already a first-class dependency
for Celery) so limits are correct across multiple backend processes/
replicas, not just per-process in-memory state. Redis is unavailable ->
fail OPEN (never block real traffic because the rate limiter's own
dependency is down) but log it, since a fail-closed rate limiter would
turn an infra blip into a full outage.
"""
import time

import redis.asyncio as aioredis
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.logging import get_logger

logger = get_logger("core.rate_limit")

# Unauthenticated auth endpoints get a stricter limit -- these are the ones
# credential-stuffing / brute-force traffic actually targets.
_STRICT_PREFIXES = ("/api/v1/auth/login", "/api/v1/auth/register")


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        redis_url: str,
        default_limit: int = 120,
        strict_limit: int = 10,
        window_seconds: int = 60,
    ) -> None:
        super().__init__(app)
        self._redis: aioredis.Redis | None = None
        self._redis_url = redis_url
        self._default_limit = default_limit
        self._strict_limit = strict_limit
        self._window_seconds = window_seconds

    def _client(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
        return self._redis

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in ("/health", "/ready", "/metrics"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        strict = request.url.path.startswith(_STRICT_PREFIXES)
        limit = self._strict_limit if strict else self._default_limit
        window = int(time.time()) // self._window_seconds
        key = f"ratelimit:{'strict' if strict else 'default'}:{client_ip}:{window}"

        try:
            redis_client = self._client()
            count = await redis_client.incr(key)
            if count == 1:
                await redis_client.expire(key, self._window_seconds)
        except Exception as exc:  # noqa: BLE001
            # Fail open: a Redis outage must not take down the whole API.
            logger.warning("rate_limit_backend_unavailable", error=str(exc))
            return await call_next(request)

        if count > limit:
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "rate_limited",
                        "message": f"Too many requests. Limit is {limit} per {self._window_seconds}s.",
                    }
                },
                headers={"Retry-After": str(self._window_seconds)},
            )

        return await call_next(request)
