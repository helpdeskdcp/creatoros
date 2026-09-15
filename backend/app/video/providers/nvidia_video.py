"""Thin client for an NVIDIA NIM video-generation endpoint (Cosmos family),
verified against NVIDIA's official docs at
docs.nvidia.com/nim/cosmos/latest/api-reference.html -- not guessed.

Unlike OpenRouter's submit-then-poll API, NVIDIA's documented /v1/infer
call is SYNCHRONOUS: it blocks until the video is ready and returns it
inline as a base64 string (no job id, no polling endpoint). To fit the
same submit_job/poll_job/download_content shape every other part of this
codebase already expects (app.video.providers.openrouter_video), this
provider does the real work in submit_job -- makes the blocking call,
decodes the result, and writes it to a scratch file under a synthetic
provider_job_id -- and poll_job/download_content simply report and return
that already-finished result. Nothing above this layer needs to know the
underlying call was synchronous.

There is no NVIDIA-operated shared endpoint this defaults to: NVIDIA's own
documentation describes Cosmos as a self-hosted NIM container
(http://localhost:8000 in their own examples). settings.nvidia_video_base_url
must be pointed at a NIM instance the operator actually runs or has access
to before this provider can do anything real.
"""
import base64
import os
import uuid

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
from app.video.providers.openrouter_video import VideoGenerationJobResult

# Generously long: unlike OpenRouter's "accept and return immediately" 202,
# this single call blocks for the entire generation.
_INFER_TIMEOUT_S = 300.0
_DOWNLOAD_TIMEOUT_S = 120.0


class NVIDIAVideoProvider:
    name = "nvidia"

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.nvidia_api_key
        self._base_url = settings.nvidia_video_base_url.rstrip("/")
        self._model = settings.nvidia_video_model
        self._scratch_dir = os.path.join(settings.storage_local_path, "_tmp_nvidia_generation")

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _redact(self, text: str) -> str:
        if self._api_key and self._api_key in text:
            return text.replace(self._api_key, "***REDACTED***")
        return text

    def _scratch_path(self, provider_job_id: str) -> str:
        return os.path.join(self._scratch_dir, f"{provider_job_id}.mp4")

    async def submit_job(self, payload: dict) -> VideoGenerationJobResult:
        """Does the entire real generation synchronously -- see module
        docstring. `payload` is a generic dict (prompt/image/resolution/
        duration/fps); translated here into Cosmos3-Generator's documented
        field names, the most general-purpose current Cosmos model
        (supports both text-to-video and image-to-video)."""
        if not self._model:
            raise AIProviderUnavailableError("NVIDIA_VIDEO_MODEL is not configured")

        body: dict = {}
        if payload.get("prompt"):
            body["prompt"] = payload["prompt"]
        if payload.get("image"):
            body["image"] = payload["image"]
        if payload.get("resolution"):
            body["resolution"] = str(payload["resolution"])
        if payload.get("duration") and payload.get("fps"):
            body["num_output_frames"] = int(payload["duration"]) * int(payload["fps"])
        if payload.get("fps"):
            body["fps"] = payload["fps"]
        if payload.get("seed") is not None:
            body["seed"] = payload["seed"]

        try:
            async with httpx.AsyncClient(timeout=_INFER_TIMEOUT_S) as client:
                resp = await client.post(f"{self._base_url}/v1/infer", json=body, headers=self._headers())
        except httpx.ReadTimeout as exc:
            # NOTE (idempotency, section on cost safety): a timeout here is
            # genuinely ambiguous -- the NIM instance may have completed
            # generation server-side despite the client not seeing the
            # response. The existing per-model retry budget
            # (_MAX_RETRIES_PER_MODEL in app.modules.video_generation.service)
            # would still retry a plain AIGenerationTimeoutError once before
            # escalating. If this provider is ever pointed at a metered/paid
            # NIM deployment, an operator relying on retry-after-timeout
            # should confirm their NIM deployment's own idempotency handling
            # (or front it with a gateway that dedupes by request id) --
            # this client does not fabricate one, since NVIDIA's documented
            # /v1/infer has no request-id/idempotency-key field to attach.
            raise AIGenerationTimeoutError(
                f"NVIDIA video generation did not complete within {_INFER_TIMEOUT_S:.0f}s"
            ) from exc
        except httpx.TransportError as exc:
            raise AIProviderUnavailableError(f"NVIDIA video endpoint unreachable: {self._base_url}") from exc

        self._raise_for_status(resp, model=self._model)
        response_body = resp.json()
        b64_video = response_body.get("b64_video")
        if not b64_video:
            raise AIProviderError("NVIDIA video response did not include b64_video")

        provider_job_id = str(uuid.uuid4())
        os.makedirs(self._scratch_dir, exist_ok=True)
        scratch_path = self._scratch_path(provider_job_id)
        tmp_path = f"{scratch_path}.part"
        try:
            video_bytes = base64.b64decode(b64_video)
        except (ValueError, TypeError) as exc:
            raise AIProviderError("NVIDIA video response contained invalid base64 data") from exc
        with open(tmp_path, "wb") as f:
            f.write(video_bytes)
        os.replace(tmp_path, scratch_path)  # atomic -- a reader never sees a partial file

        return VideoGenerationJobResult(
            provider_job_id=provider_job_id, status="pending", unsigned_urls=[], cost=None, error=None,
        )

    async def poll_job(self, provider_job_id: str) -> VideoGenerationJobResult:
        """The real work already happened in submit_job (see module
        docstring) -- this just reports that the scratch file is ready."""
        if os.path.isfile(self._scratch_path(provider_job_id)):
            return VideoGenerationJobResult(provider_job_id=provider_job_id, status="completed")
        return VideoGenerationJobResult(
            provider_job_id=provider_job_id, status="failed",
            error="NVIDIA-generated video file was not found (already downloaded, or generation never completed)",
        )

    async def download_content(self, provider_job_id: str, local_path: str, *, index: int = 0) -> int:
        scratch_path = self._scratch_path(provider_job_id)
        if not os.path.isfile(scratch_path):
            raise AIProviderError(f"No NVIDIA-generated video found for job {provider_job_id}")
        size = os.path.getsize(scratch_path)
        os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
        os.replace(scratch_path, local_path)  # move, not copy -- never leak scratch files
        return size

    async def download_from_url(self, url: str, local_path: str) -> int:
        """Interface parity with OpenRouterVideoProvider -- never actually
        invoked in the current flow, since NVIDIA's response never
        populates unsigned_urls (see submit_job), but implemented for real
        in case a future Cosmos variant returns a URL instead of base64."""
        written = 0
        try:
            async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT_S) as client:
                async with client.stream("GET", url) as resp:
                    if resp.status_code != 200:
                        raise AIProviderError(f"NVIDIA video output URL returned HTTP {resp.status_code}")
                    os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
                    with open(local_path, "wb") as f:
                        async for chunk in resp.aiter_bytes():
                            f.write(chunk)
                            written += len(chunk)
        except httpx.ReadTimeout as exc:
            raise AIGenerationTimeoutError("NVIDIA video output download did not complete in time") from exc
        except httpx.TransportError as exc:
            raise AIProviderUnavailableError(f"NVIDIA video output URL unreachable: {url}") from exc
        return written

    def _raise_for_status(self, resp: httpx.Response, *, model: str | None) -> None:
        if resp.status_code == 200:
            return
        if resp.status_code == 404:
            raise ModelNotAvailableError(f"NVIDIA model '{model}' is not available at {self._base_url}")
        if resp.status_code == 429:
            retry_after = resp.headers.get("retry-after")
            suffix = f" (retry after {retry_after}s)" if retry_after else ""
            raise RateLimitedError(f"Provider 'nvidia' rate-limited this video request{suffix}")
        if resp.status_code in (401, 403):
            raise AIProviderError(f"Provider 'nvidia' rejected the video request: HTTP {resp.status_code}")
        if resp.status_code == 402:
            raise InsufficientCreditsError("Insufficient NVIDIA credits/quota for this video request")
        raise AIProviderError(f"NVIDIA video API returned {resp.status_code}: {self._redact(resp.text)}")
