"""Thin client for Pexels' real search API, verified live against the
actual endpoints (not guessed): GET https://api.pexels.com/v1/search
(photos) and GET https://api.pexels.com/videos/search (videos), auth via
a plain `Authorization: <key>` header (no "Bearer " prefix -- Pexels'
own convention, confirmed by a real 200 response). Genuinely free: no
credit metering, a generous monthly rate limit reported back in
X-Ratelimit-* response headers.

Search results are read-only and cost nothing; downloading a specific
photo/video's bytes (see service.import_from_pexels) is the only
"heavier" operation, and even that is free per Pexels' terms -- just
real bandwidth, not billed credits.
"""
import httpx

from app.ai.providers.base import AIProviderError, AIProviderUnavailableError, RateLimitedError
from app.core.config import Settings

_TIMEOUT_S = 20.0
_DOWNLOAD_TIMEOUT_S = 60.0


def _headers(settings: Settings) -> dict:
    return {"Authorization": settings.pexels_api_key}


def _raise_for_status(resp: httpx.Response) -> None:
    if resp.status_code == 200:
        return
    if resp.status_code == 429:
        raise RateLimitedError("Pexels rate-limited this request")
    if resp.status_code in (401, 403):
        raise AIProviderError(f"Pexels rejected the request: HTTP {resp.status_code}")
    raise AIProviderError(f"Pexels API returned {resp.status_code}")


def _normalize_photo(raw: dict) -> dict:
    src = raw.get("src") or {}
    return {
        "id": raw.get("id"),
        "width": raw.get("width"),
        "height": raw.get("height"),
        "photographer": raw.get("photographer"),
        "photographer_url": raw.get("photographer_url"),
        "page_url": raw.get("url"),
        "thumbnail_url": src.get("medium"),
        "download_url": src.get("large") or src.get("original"),
    }


def _normalize_video(raw: dict) -> dict:
    files = sorted(
        (raw.get("video_files") or []), key=lambda f: (f.get("width") or 0) * (f.get("height") or 0), reverse=True
    )
    best = files[0] if files else {}
    return {
        "id": raw.get("id"),
        "duration": raw.get("duration"),
        "width": raw.get("width"),
        "height": raw.get("height"),
        "user": (raw.get("user") or {}).get("name"),
        "page_url": raw.get("url"),
        "thumbnail_url": raw.get("image"),
        "download_url": best.get("link"),
    }


async def search_photos(settings: Settings, query: str, *, per_page: int = 15, page: int = 1) -> list[dict]:
    if not settings.pexels_configured:
        raise AIProviderUnavailableError("PEXELS_API_KEY is not configured")
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            resp = await client.get(
                "https://api.pexels.com/v1/search",
                headers=_headers(settings),
                params={"query": query, "per_page": per_page, "page": page},
            )
    except httpx.TransportError as exc:
        raise AIProviderUnavailableError("Pexels endpoint unreachable") from exc
    _raise_for_status(resp)
    return [_normalize_photo(p) for p in resp.json().get("photos", [])]


async def search_videos(settings: Settings, query: str, *, per_page: int = 15, page: int = 1) -> list[dict]:
    if not settings.pexels_configured:
        raise AIProviderUnavailableError("PEXELS_API_KEY is not configured")
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            resp = await client.get(
                "https://api.pexels.com/videos/search",
                headers=_headers(settings),
                params={"query": query, "per_page": per_page, "page": page},
            )
    except httpx.TransportError as exc:
        raise AIProviderUnavailableError("Pexels endpoint unreachable") from exc
    _raise_for_status(resp)
    return [_normalize_video(v) for v in resp.json().get("videos", [])]


async def download_to_file(url: str, local_path: str) -> int:
    """Streams a Pexels-hosted photo/video's real bytes to `local_path` --
    these CDN URLs are plain and unauthenticated (no Pexels key needed or
    sent), same as OpenRouter's/Magic Hour's unsigned output URLs."""
    written = 0
    try:
        async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT_S) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    raise AIProviderError(f"Pexels download URL returned HTTP {resp.status_code}")
                with open(local_path, "wb") as f:
                    async for chunk in resp.aiter_bytes():
                        f.write(chunk)
                        written += len(chunk)
    except httpx.TransportError as exc:
        raise AIProviderUnavailableError(f"Pexels download URL unreachable: {url}") from exc
    return written
