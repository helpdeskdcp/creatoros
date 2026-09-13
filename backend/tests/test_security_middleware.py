"""Coverage for the security-headers and rate-limiting middleware added to
close two gaps the production audit confirmed: no CSP/HSTS/frame-options
at all, and no application-level rate limiting."""
import pytest

from app.core.rate_limit import RateLimitMiddleware


@pytest.mark.asyncio
async def test_security_headers_present_on_every_response(client):
    resp = await client.get("/api/v1/channels/oauth/status")
    # 401 (no auth) is fine -- headers must be present regardless of status.
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert resp.headers["Content-Security-Policy"] == "default-src 'none'; frame-ancestors 'none'"


@pytest.mark.asyncio
async def test_rate_limit_fails_open_when_redis_unreachable(client, unique_email):
    # conftest points REDIS_URL at an unreachable address on purpose --
    # a Redis outage must never take down the whole API.
    resp = await client.post(
        "/api/v1/auth/register", json={"email": unique_email, "password": "supersecurepassword1"}
    )
    assert resp.status_code == 201


class _FakeRedis:
    """Minimal in-memory stand-in for the two Redis commands the limiter
    uses, so the actual counting/blocking logic can be tested without a
    real Redis server."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, seconds: int) -> None:
        return None


async def _call_next(request):
    from starlette.responses import PlainTextResponse

    return PlainTextResponse("ok")


def _make_request(path: str):
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
        "client": ("1.2.3.4", 12345),
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_rate_limit_blocks_after_threshold():
    middleware = RateLimitMiddleware(app=None, redis_url="redis://unused/0", default_limit=3, window_seconds=60)
    middleware._redis = _FakeRedis()  # inject fake backend directly, no network

    request = _make_request("/api/v1/channels")
    responses = [await middleware.dispatch(request, _call_next) for _ in range(4)]

    statuses = [r.status_code for r in responses]
    assert statuses == [200, 200, 200, 429]
    assert responses[-1].headers["Retry-After"] == "60"


@pytest.mark.asyncio
async def test_rate_limit_strict_threshold_for_auth_endpoints():
    middleware = RateLimitMiddleware(
        app=None, redis_url="redis://unused/0", default_limit=120, strict_limit=2, window_seconds=60
    )
    middleware._redis = _FakeRedis()

    request = _make_request("/api/v1/auth/login")
    responses = [await middleware.dispatch(request, _call_next) for _ in range(3)]

    assert [r.status_code for r in responses] == [200, 200, 429]


@pytest.mark.asyncio
async def test_rate_limit_exempts_observability_endpoints():
    middleware = RateLimitMiddleware(app=None, redis_url="redis://unused/0", default_limit=1, window_seconds=60)
    middleware._redis = _FakeRedis()

    request = _make_request("/health")
    responses = [await middleware.dispatch(request, _call_next) for _ in range(5)]

    assert all(r.status_code == 200 for r in responses)
