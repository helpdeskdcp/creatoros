"""Thin client for OpenRouter's real video-generation API (POST /videos,
GET /videos/{jobId}, GET /videos/{jobId}/content) -- verified against the
live OpenAPI spec at https://openrouter.ai/openapi.json, not guessed.
Nothing above this layer (app.video.router, the Celery task) constructs
this request shape itself; they call submit_job/poll_job/download_content.
"""
from dataclasses import dataclass, field

import httpx

from app.ai.providers.base import (
    AIGenerationTimeoutError,
    AIProviderError,
    AIProviderUnavailableError,
    ModelNotAvailableError,
    RateLimitedError,
)
from app.core.config import Settings

_SUBMIT_TIMEOUT_S = 30.0
_POLL_TIMEOUT_S = 20.0
_DOWNLOAD_TIMEOUT_S = 120.0

TERMINAL_STATUSES = {"completed", "failed", "cancelled", "expired"}


@dataclass
class VideoGenerationJobResult:
    provider_job_id: str
    status: str
    unsigned_urls: list[str] = field(default_factory=list)
    cost: float | None = None
    error: str | None = None


class OpenRouterVideoProvider:
    name = "openrouter"

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.openrouter_api_key
        self._base_url = settings.openrouter_base_url.rstrip("/")

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    def _redact(self, text: str) -> str:
        if self._api_key and self._api_key in text:
            return text.replace(self._api_key, "***REDACTED***")
        return text

    async def submit_job(self, payload: dict) -> VideoGenerationJobResult:
        if not self._api_key:
            raise AIProviderUnavailableError("OPENROUTER_API_KEY is not configured")
        try:
            async with httpx.AsyncClient(timeout=_SUBMIT_TIMEOUT_S) as client:
                resp = await client.post(
                    f"{self._base_url}/videos", json=payload, headers=self._headers()
                )
        except httpx.ReadTimeout as exc:
            raise AIGenerationTimeoutError("Video submission did not respond in time") from exc
        except httpx.TransportError as exc:
            raise AIProviderUnavailableError(f"Video endpoint unreachable: {self._base_url}") from exc

        self._raise_for_status(resp, model=payload.get("model"))
        body = resp.json()
        return VideoGenerationJobResult(
            provider_job_id=body["id"],
            status=body["status"],
            unsigned_urls=body.get("unsigned_urls") or [],
            cost=(body.get("usage") or {}).get("cost"),
            error=body.get("error"),
        )

    async def poll_job(self, provider_job_id: str) -> VideoGenerationJobResult:
        if not self._api_key:
            raise AIProviderUnavailableError("OPENROUTER_API_KEY is not configured")
        try:
            async with httpx.AsyncClient(timeout=_POLL_TIMEOUT_S) as client:
                resp = await client.get(
                    f"{self._base_url}/videos/{provider_job_id}", headers=self._headers()
                )
        except httpx.ReadTimeout as exc:
            raise AIGenerationTimeoutError("Video status poll did not respond in time") from exc
        except httpx.TransportError as exc:
            raise AIProviderUnavailableError(f"Video endpoint unreachable: {self._base_url}") from exc

        self._raise_for_status(resp, model=None)
        body = resp.json()
        return VideoGenerationJobResult(
            provider_job_id=body["id"],
            status=body["status"],
            unsigned_urls=body.get("unsigned_urls") or [],
            cost=(body.get("usage") or {}).get("cost"),
            error=body.get("error"),
        )

    async def download_content(self, provider_job_id: str, local_path: str, *, index: int = 0) -> int:
        """Streams the generated video to `local_path` (never fully
        buffered in memory) and returns the byte count written. Used as a
        fallback when `unsigned_urls` isn't populated -- the content
        endpoint proxies the same bytes directly through OpenRouter."""
        if not self._api_key:
            raise AIProviderUnavailableError("OPENROUTER_API_KEY is not configured")
        url = f"{self._base_url}/videos/{provider_job_id}/content"
        written = 0
        try:
            async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT_S) as client:
                async with client.stream("GET", url, params={"index": index}, headers=self._headers()) as resp:
                    if resp.status_code != 200:
                        # Never call resp.text on a streamed response before
                        # it's read (raises httpx.ResponseNotRead) -- and no
                        # caller needs the body detail for a download failure.
                        self._raise_for_status_code(resp.status_code, resp.headers, model=None)
                    with open(local_path, "wb") as f:
                        async for chunk in resp.aiter_bytes():
                            f.write(chunk)
                            written += len(chunk)
        except httpx.ReadTimeout as exc:
            raise AIGenerationTimeoutError("Video download did not complete in time") from exc
        except httpx.TransportError as exc:
            raise AIProviderUnavailableError(f"Video endpoint unreachable: {self._base_url}") from exc
        return written

    async def download_from_url(self, url: str, local_path: str) -> int:
        """Downloads from one of the response's `unsigned_urls` -- these
        are plain, unauthenticated storage URLs (no OpenRouter key needed
        or sent)."""
        written = 0
        try:
            async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT_S) as client:
                async with client.stream("GET", url) as resp:
                    if resp.status_code != 200:
                        raise AIProviderError(f"Video output URL returned HTTP {resp.status_code}")
                    with open(local_path, "wb") as f:
                        async for chunk in resp.aiter_bytes():
                            f.write(chunk)
                            written += len(chunk)
        except httpx.ReadTimeout as exc:
            raise AIGenerationTimeoutError("Video output download did not complete in time") from exc
        except httpx.TransportError as exc:
            raise AIProviderUnavailableError(f"Video output URL unreachable: {url}") from exc
        return written

    def _raise_for_status(self, resp: httpx.Response, *, model: str | None) -> None:
        if resp.status_code in (200, 202):
            return
        if resp.status_code not in (404, 429, 401, 403, 402):
            raise AIProviderError(
                f"OpenRouter video API returned {resp.status_code}: {self._redact(resp.text)}"
            )
        self._raise_for_status_code(resp.status_code, resp.headers, model=model)

    def _raise_for_status_code(self, status_code: int, headers, *, model: str | None) -> None:
        """Status-only variant safe to call on a not-yet-read streamed
        response (never touches the response body)."""
        if status_code == 404:
            raise ModelNotAvailableError(
                f"Model '{model}' is not available for video generation" if model else "Video job not found"
            )
        if status_code == 429:
            retry_after = headers.get("retry-after")
            suffix = f" (retry after {retry_after}s)" if retry_after else ""
            raise RateLimitedError(f"Provider 'openrouter' rate-limited this video request{suffix}")
        if status_code in (401, 403):
            raise AIProviderError(f"Provider 'openrouter' rejected the video request: HTTP {status_code}")
        if status_code == 402:
            raise AIProviderError("Insufficient OpenRouter credits for this video request")
        raise AIProviderError(f"OpenRouter video API returned {status_code}")
