"""Thin client for Magic Hour's real video-generation API, verified
against docs.magichour.ai (not guessed):
  POST {base}/text-to-video   or  POST {base}/image-to-video
    -> 200 {"id": "...", "credits_charged": N}
  GET  {base}/video-projects/{id}
    -> {"status": "draft"|"queued"|"rendering"|"complete"|"error"|"canceled",
        "error": {"message", "code"} | null,
        "downloads": [{"url": "...", "expires_at": "..."}]}

A genuinely async, hosted REST API -- much closer in shape to
OpenRouterVideoProvider than NVIDIA's synchronous self-hosted /v1/infer,
so submit_job/poll_job map onto Magic Hour's real endpoints directly with
no synthetic bridging needed.
"""
from dataclasses import dataclass, field

import httpx

from app.ai.providers.base import (
    AIGenerationTimeoutError,
    AIProviderError,
    AIProviderUnavailableError,
    InsufficientCreditsError,
    ModelNotAvailableError,
    RateLimitedError,
)
from app.core.config import Settings

_SUBMIT_TIMEOUT_S = 30.0
_POLL_TIMEOUT_S = 20.0
_DOWNLOAD_TIMEOUT_S = 120.0

# Magic Hour's own terminal/non-terminal status vocabulary (see module
# docstring) -- distinct spelling/values from OpenRouter's, mapped in
# poll_job rather than reused directly.
_PENDING_STATUSES = {"draft", "queued"}
_IN_PROGRESS_STATUSES = {"rendering"}


@dataclass
class VideoGenerationJobResult:
    provider_job_id: str
    status: str
    unsigned_urls: list[str] = field(default_factory=list)
    cost: float | None = None
    error: str | None = None


class MagicHourVideoProvider:
    name = "magichour"

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.magic_hour_api_key
        self._base_url = settings.magic_hour_base_url.rstrip("/")

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    def _redact(self, text: str) -> str:
        if self._api_key and self._api_key in text:
            return text.replace(self._api_key, "***REDACTED***")
        return text

    async def submit_job(self, payload: dict) -> VideoGenerationJobResult:
        if not self._api_key:
            raise AIProviderUnavailableError("MAGIC_HOUR_API_KEY is not configured")
        # image_file_path accepts a direct external URL just as well as a
        # Magic Hour-hosted upload's file_path (confirmed in their API
        # reference) -- CreatorOS's plain input-reference URLs work as-is,
        # no separate upload step needed.
        image_url = payload.get("image")
        endpoint = "image-to-video" if image_url else "text-to-video"
        body: dict = {"end_seconds": payload.get("duration") or 5}
        if payload.get("model"):
            body["model"] = payload["model"]
        if payload.get("resolution"):
            body["resolution"] = payload["resolution"]
        if payload.get("aspect_ratio"):
            body["aspect_ratio"] = payload["aspect_ratio"]
        if payload.get("audio"):
            body["audio"] = True
        if payload.get("prompt"):
            body["style"] = {"prompt": payload["prompt"]}
        if image_url:
            body["assets"] = {"image_file_path": image_url}

        try:
            async with httpx.AsyncClient(timeout=_SUBMIT_TIMEOUT_S) as client:
                resp = await client.post(f"{self._base_url}/{endpoint}", json=body, headers=self._headers())
        except httpx.ReadTimeout as exc:
            raise AIGenerationTimeoutError("Magic Hour video submission did not respond in time") from exc
        except httpx.TransportError as exc:
            raise AIProviderUnavailableError(f"Magic Hour endpoint unreachable: {self._base_url}") from exc

        self._raise_for_status(resp, model=payload.get("model"))
        result = resp.json()
        return VideoGenerationJobResult(
            provider_job_id=result["id"], status="pending", cost=result.get("credits_charged"),
        )

    async def poll_job(self, provider_job_id: str) -> VideoGenerationJobResult:
        if not self._api_key:
            raise AIProviderUnavailableError("MAGIC_HOUR_API_KEY is not configured")
        try:
            async with httpx.AsyncClient(timeout=_POLL_TIMEOUT_S) as client:
                resp = await client.get(
                    f"{self._base_url}/video-projects/{provider_job_id}", headers=self._headers()
                )
        except httpx.ReadTimeout as exc:
            raise AIGenerationTimeoutError("Magic Hour status poll did not respond in time") from exc
        except httpx.TransportError as exc:
            raise AIProviderUnavailableError(f"Magic Hour endpoint unreachable: {self._base_url}") from exc

        self._raise_for_status(resp, model=None)
        body = resp.json()
        raw_status = body.get("status", "")
        if raw_status in _PENDING_STATUSES:
            status = "pending"
        elif raw_status in _IN_PROGRESS_STATUSES:
            status = "in_progress"
        elif raw_status == "complete":
            status = "completed"
        else:
            # "error" / "canceled" / anything unrecognized -- fall through
            # to the pipeline's generic failed/cancelled handling, never
            # silently treated as still-in-progress.
            status = raw_status or "failed"

        downloads = body.get("downloads") or []
        error_obj = body.get("error") or {}
        return VideoGenerationJobResult(
            provider_job_id=provider_job_id,
            status=status,
            unsigned_urls=[d["url"] for d in downloads if d.get("url")],
            cost=body.get("credits_charged"),
            error=error_obj.get("message"),
        )

    async def download_content(self, provider_job_id: str, local_path: str, *, index: int = 0) -> int:
        """Magic Hour always returns its output via `downloads` URLs in
        poll_job -- this path (used only when unsigned_urls is empty) is
        never expected to be hit; kept for interface parity."""
        raise AIProviderError(f"No downloadable output URL was returned for job {provider_job_id}")

    async def download_from_url(self, url: str, local_path: str) -> int:
        written = 0
        try:
            async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT_S) as client:
                async with client.stream("GET", url) as resp:
                    if resp.status_code != 200:
                        raise AIProviderError(f"Magic Hour video output URL returned HTTP {resp.status_code}")
                    with open(local_path, "wb") as f:
                        async for chunk in resp.aiter_bytes():
                            f.write(chunk)
                            written += len(chunk)
        except httpx.ReadTimeout as exc:
            raise AIGenerationTimeoutError("Magic Hour video output download did not complete in time") from exc
        except httpx.TransportError as exc:
            raise AIProviderUnavailableError(f"Magic Hour video output URL unreachable: {url}") from exc
        return written

    def _raise_for_status(self, resp: httpx.Response, *, model: str | None) -> None:
        if resp.status_code == 200:
            return
        if resp.status_code == 404:
            raise ModelNotAvailableError(
                f"Magic Hour model '{model}' or job is not available" if model else "Magic Hour job not found"
            )
        if resp.status_code == 429:
            raise RateLimitedError("Provider 'magichour' rate-limited this video request")
        if resp.status_code in (401, 403):
            raise AIProviderError(f"Provider 'magichour' rejected the video request: HTTP {resp.status_code}")
        if resp.status_code == 402:
            # Magic Hour's own documented 402 sub-reasons: insufficient_credits,
            # subscription_required, plan_upgrade_required -- all billing, none
            # of them a model/privacy problem.
            raise InsufficientCreditsError("Insufficient Magic Hour credits/plan for this video request")
        raise AIProviderError(f"Magic Hour video API returned {resp.status_code}: {self._redact(resp.text)}")
