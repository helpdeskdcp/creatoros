"""Live OpenRouter video-model catalog discovery.

The live API (GET /videos/models) is the ONLY source of truth for what a
model supports -- this module never hard-codes "model X supports Y". It
fetches the real catalog, normalizes it into VideoModelCatalogEntry rows,
and diffs against what's already stored: new models are added, models that
stopped appearing are marked inactive (never deleted -- historical VideoJob
rows must keep a resolvable model name), and changed capabilities are
updated in place. Call refresh_catalog() at startup and on a schedule
(see app.jobs.tasks.refresh_video_model_catalog_task, every 30 min).
"""
import json
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers.base import AIProviderUnavailableError
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.video.models import CircuitState, VideoModelCatalogEntry

logger = get_logger("video.catalog")

_TIMEOUT_S = 30.0

# A model whose description contains any of these phrases is understood to
# be image/video-input-only (no meaningful text-to-video path) -- inferred
# from the live catalog's free-text `description` field, since OpenRouter
# exposes no explicit boolean for this. Kept short and conservative: a
# false negative here (treating a text-capable model as image-only) just
# means it's under-routed for text_to_video requests, never mis-routed
# into an invalid submission -- the live API call is still the final gate.
_IMAGE_ONLY_PHRASES = (
    "image-to-video model", "animates a single photo",
    "video editing model", "video-editing model", "upscal",
)

# Maintained quality heuristic -- NOT sourced from OpenRouter, which
# exposes no quality signal. Documented here so routing decisions can be
# explained honestly rather than presented as API-confirmed fact. Any
# model not listed falls back to _DEFAULT_QUALITY_SCORE, so a newly
# discovered model is never unroutable while this table catches up.
_DEFAULT_QUALITY_SCORE = 0.6
QUALITY_TIERS: dict[str, float] = {
    "google/veo-3.1": 1.0,
    "google/veo-3.1-fast": 0.9,
    "google/veo-3.1-lite": 0.8,
    "openai/sora-2-pro": 1.0,
    "kwaivgi/kling-v3.0-pro": 0.9,
    "kwaivgi/kling-v3.0-std": 0.78,
    "kwaivgi/kling-video-o1": 0.82,
    "bytedance/seedance-2.5": 0.88,
    "bytedance/seedance-2.0": 0.85,
    "bytedance/seedance-2.0-mini": 0.7,
    "bytedance/seedance-2.0-fast": 0.72,
    "bytedance/seedance-1-5-pro": 0.8,
    "alibaba/wan-3.0-prime": 0.85,
    "alibaba/wan-3.0": 0.75,
    "alibaba/wan-2.7": 0.7,
    "alibaba/wan-2.6": 0.65,
    "alibaba/happyhorse-1.1": 0.68,
    "alibaba/happyhorse-1.0": 0.63,
    "minimax/hailuo-3": 0.82,
    "minimax/hailuo-3-max": 0.86,
    "minimax/hailuo-2.3": 0.68,
    "runway/gen-4.5": 0.8,
    "runway/aleph-2": 0.72,
    "x-ai/grok-imagine-video-1.5": 0.75,
    "x-ai/grok-imagine-video": 0.68,
    "heygen/avatar-iv": 0.7,
}


class CatalogFetchError(Exception):
    """The live GET /videos/models call itself failed (network/auth/5xx).
    Distinct from a parsing problem with one model entry, which is skipped
    rather than failing the whole refresh."""


async def fetch_raw_catalog(settings: Settings) -> list[dict]:
    if not settings.openrouter_api_key:
        raise AIProviderUnavailableError("OPENROUTER_API_KEY is not configured")
    url = f"{settings.openrouter_base_url.rstrip('/')}/videos/models"
    headers = {"Authorization": f"Bearer {settings.openrouter_api_key}"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            resp = await client.get(url, headers=headers)
    except httpx.TransportError as exc:
        raise CatalogFetchError(f"OpenRouter video catalog endpoint unreachable: {url}") from exc
    if resp.status_code != 200:
        # Never include resp.text raw -- defense in depth against an
        # upstream error body ever echoing the Authorization header back,
        # exactly like app.ai.providers.openai_compat's redaction policy.
        raise CatalogFetchError(f"GET /videos/models returned HTTP {resp.status_code}")
    body = resp.json()
    return body.get("data", [])


def _infer_text_to_video(description: str | None) -> bool:
    if not description:
        return True
    lowered = description.lower()
    return not any(phrase in lowered for phrase in _IMAGE_ONLY_PHRASES)


def _is_free(pricing_skus: dict) -> bool:
    if not pricing_skus:
        return False
    try:
        return all(float(v) == 0.0 for v in pricing_skus.values())
    except (TypeError, ValueError):
        return False


def normalize_model(raw: dict) -> dict:
    """Pure function: raw OpenRouter catalog entry -> normalized fields
    matching VideoModelCatalogEntry's columns. Separated from the DB layer
    so capability-inference logic is unit-testable without a database."""
    model_id = raw["id"]
    provider = model_id.split("/", 1)[0] if "/" in model_id else "unknown"
    pricing_skus = raw.get("pricing_skus") or {}
    description = raw.get("description")
    return {
        "model_id": model_id,
        "name": raw.get("name") or model_id,
        "provider": provider,
        "description": description,
        "supported_resolutions_json": json.dumps(raw.get("supported_resolutions")),
        "supported_aspect_ratios_json": json.dumps(raw.get("supported_aspect_ratios")),
        "supported_durations_json": json.dumps(raw.get("supported_durations")),
        "supported_frame_images_json": json.dumps(raw.get("supported_frame_images")),
        "supports_audio": bool(raw.get("generate_audio")),
        # Per OpenRouter's InputReference schema docs: image references are
        # accepted by every provider -- not a per-model inference.
        "supports_image_reference": True,
        "supports_text_to_video": _infer_text_to_video(description),
        "pricing_skus_json": json.dumps(pricing_skus),
        "is_free": _is_free(pricing_skus),
        # OpenRouter's live pricing_skus always resolves confidently --
        # never UNKNOWN for this provider (see pricing_status's docstring
        # on VideoModelCatalogEntry).
        "pricing_status": "FREE" if _is_free(pricing_skus) else "PAID",
        "quality_tier_score": QUALITY_TIERS.get(model_id, _DEFAULT_QUALITY_SCORE),
    }


async def refresh_catalog(db: AsyncSession, settings: Settings | None = None) -> dict:
    """Fetches the live catalog and reconciles it against the DB. Returns a
    summary dict {added, updated, deactivated, total_active} for logging/
    the admin dashboard -- never raises for a single bad model entry
    (skipped + logged), only for a total fetch failure."""
    settings = settings or get_settings()
    raw_models = await fetch_raw_catalog(settings)
    now = datetime.now(UTC)

    existing_rows = (await db.scalars(select(VideoModelCatalogEntry))).all()
    existing_by_id = {row.model_id: row for row in existing_rows}
    seen_ids: set[str] = set()

    added = 0
    updated = 0
    for raw in raw_models:
        try:
            normalized = normalize_model(raw)
        except (KeyError, TypeError) as exc:
            logger.warning("video_catalog_entry_skipped", error=str(exc), raw_id=raw.get("id"))
            continue
        model_id = normalized["model_id"]
        seen_ids.add(model_id)
        row = existing_by_id.get(model_id)
        if row is None:
            row = VideoModelCatalogEntry(**normalized, is_active=True, last_checked_at=now)
            db.add(row)
            added += 1
        else:
            for field, value in normalized.items():
                setattr(row, field, value)
            row.is_active = True
            row.last_checked_at = now
            updated += 1

    deactivated = 0
    for model_id, row in existing_by_id.items():
        if model_id not in seen_ids and row.is_active:
            row.is_active = False
            deactivated += 1

    await db.commit()
    summary = {
        "added": added,
        "updated": updated,
        "deactivated": deactivated,
        "total_active": len(seen_ids),
    }
    logger.info("video_catalog_refreshed", **summary)
    return summary


async def refresh_nvidia_catalog(db: AsyncSession, settings: Settings | None = None) -> dict:
    """Upserts (or deactivates) the single configured NVIDIA video model.

    Unlike refresh_catalog()'s OpenRouter path, this is NOT live discovery
    -- NVIDIA's documented API (docs.nvidia.com/nim/cosmos) exposes no
    "list models with capabilities/pricing" endpoint the way OpenRouter's
    GET /videos/models does, so there is nothing to fetch and parse.
    Instead this seeds exactly one row per NVIDIA_VIDEO_MODEL, entirely
    from config, and is_active tracks nvidia_video_configured directly:
    disable NVIDIA_VIDEO_ENABLED (or unset the key/model) and this call
    deactivates the row on its next run, same as an OpenRouter model that
    stopped appearing in the live catalog."""
    settings = settings or get_settings()
    model_id = f"nvidia/{settings.nvidia_video_model}" if settings.nvidia_video_model else None
    now = datetime.now(UTC)

    existing_rows = list(
        (
            await db.scalars(select(VideoModelCatalogEntry).where(VideoModelCatalogEntry.provider == "nvidia"))
        ).all()
    )

    if not settings.nvidia_video_configured or model_id is None:
        deactivated = 0
        for existing_row in existing_rows:
            if existing_row.is_active:
                existing_row.is_active = False
                deactivated += 1
        if deactivated:
            await db.commit()
        return {"added": 0, "updated": 0, "deactivated": deactivated, "total_active": 0}

    is_free = settings.nvidia_video_pricing_status == "FREE"
    row: VideoModelCatalogEntry | None = next((r for r in existing_rows if r.model_id == model_id), None)
    added, updated = 0, 0
    if row is None:
        row = VideoModelCatalogEntry(
            model_id=model_id,
            name=settings.nvidia_video_model,
            provider="nvidia",
            description="NVIDIA-hosted video generation model, configured via NVIDIA_VIDEO_MODEL.",
            supports_audio=False,
            supports_image_reference=True,
            supports_text_to_video=True,
            is_free=is_free,
            pricing_status=settings.nvidia_video_pricing_status,
            quality_tier_score=_DEFAULT_QUALITY_SCORE,
            fallback_priority=0,
            is_active=True,
            last_checked_at=now,
        )
        db.add(row)
        added = 1
    else:
        row.is_free = is_free
        row.pricing_status = settings.nvidia_video_pricing_status
        row.fallback_priority = 0
        row.is_active = True
        row.last_checked_at = now
        updated = 1

    # Any OTHER nvidia/* row (a previously configured, now-abandoned model)
    # is deactivated the same way a vanished OpenRouter model would be.
    deactivated = 0
    for other in existing_rows:
        if other.model_id != model_id and other.is_active:
            other.is_active = False
            deactivated += 1

    await db.commit()
    summary = {"added": added, "updated": updated, "deactivated": deactivated, "total_active": 1}
    logger.info("nvidia_video_catalog_refreshed", **summary)
    return summary


async def list_active_models(db: AsyncSession) -> list[VideoModelCatalogEntry]:
    models = list(
        (
            await db.scalars(
                select(VideoModelCatalogEntry).where(VideoModelCatalogEntry.is_active.is_(True))
            )
        ).all()
    )
    if recover_expired_circuits(models):
        await db.commit()
    return models


def record_success(row: VideoModelCatalogEntry, latency_ms: int, *, max_recent: int = 50) -> None:
    row.success_count += 1
    row.consecutive_failures = 0
    row.last_success_at = datetime.now(UTC)
    if row.circuit_state == CircuitState.HALF_OPEN:
        row.circuit_state = CircuitState.CLOSED
        row.circuit_opened_at = None
    recent = json.loads(row.recent_latencies_ms_json) if row.recent_latencies_ms_json else []
    recent.append(latency_ms)
    row.recent_latencies_ms_json = json.dumps(recent[-max_recent:])


def record_failure(row: VideoModelCatalogEntry, *, failure_threshold: int = 5) -> None:
    row.failure_count += 1
    row.consecutive_failures += 1
    row.last_failure_at = datetime.now(UTC)
    if row.circuit_state == CircuitState.HALF_OPEN or row.consecutive_failures >= failure_threshold:
        row.circuit_state = CircuitState.OPEN
        row.circuit_opened_at = datetime.now(UTC)


_CIRCUIT_COOLDOWN_SECONDS = 300  # 5 minutes


def recover_expired_circuits(
    models: list[VideoModelCatalogEntry], *, cooldown_seconds: int = _CIRCUIT_COOLDOWN_SECONDS
) -> int:
    """OPEN -> HALF_OPEN once the cooldown has elapsed since the circuit
    tripped -- a single "controlled probe" (the next routing attempt that
    reaches this model) decides CLOSED (record_success) or back to OPEN
    (record_failure); nothing hammers a failing provider in a tight loop.
    Called on every model list read right before routing (see
    app.modules.video_generation.service.create_video_job and
    submit_attempt) so the transition is always fresh, not dependent on a
    separate scheduled task. Returns the number of models recovered, for
    logging/observability."""
    now = datetime.now(UTC)
    recovered = 0
    for row in models:
        if (
            row.circuit_state == CircuitState.OPEN
            and row.circuit_opened_at is not None
            and (now - row.circuit_opened_at).total_seconds() >= cooldown_seconds
        ):
            row.circuit_state = CircuitState.HALF_OPEN
            recovered += 1
    return recovered


def mark_zdr_blocked(row: VideoModelCatalogEntry) -> None:
    """Reactively records that this account's current OpenRouter workspace
    guardrail rejects this model on privacy grounds (see
    app.video.providers.openrouter_video.PrivacyPolicyViolationError) --
    the only way this is ever knowable, since the catalog itself carries
    no such field. Also counts as a failure for health/circuit-breaker
    purposes: a policy-blocked model is exactly as unusable as a broken
    one from the router's perspective, just for a different reason."""
    row.known_zdr_blocked = True
    row.zdr_blocked_at = datetime.now(UTC)
    record_failure(row)


async def get_health_summary(db: AsyncSession) -> dict:
    """Section 18/22's admin/health view -- real counts from the DB, never
    a fabricated "all systems operational"."""
    all_rows = list((await db.scalars(select(VideoModelCatalogEntry))).all())
    active = [m for m in all_rows if m.is_active]
    return {
        "total_models": len(all_rows),
        "active_models": len(active),
        "inactive_models": len(all_rows) - len(active),
        "free_models": sum(1 for m in active if m.is_free),
        "zdr_blocked_models": sum(1 for m in all_rows if m.known_zdr_blocked),
        "circuit_breakers": {
            "closed": sum(1 for m in active if m.circuit_state == CircuitState.CLOSED),
            "open": sum(1 for m in active if m.circuit_state == CircuitState.OPEN),
            "half_open": sum(1 for m in active if m.circuit_state == CircuitState.HALF_OPEN),
        },
    }


def _safe_json_list(text: str | None) -> list:
    """Same null-safety as app.video.router._loads (json.dumps(None) ==
    the truthy string "null", which json.loads parses back to None, not
    [])."""
    if not text:
        return []
    value = json.loads(text)
    return value if value is not None else []


def get_capabilities_summary(models: list[VideoModelCatalogEntry]) -> dict:
    """Aggregated across every active, non-ZDR-blocked model -- what a
    caller can actually ask for right now, derived from live data rather
    than a maintained list that drifts from the real catalog."""
    resolutions: set[str] = set()
    aspect_ratios: set[str] = set()
    durations: set[int] = set()
    generation_types: set[str] = set()
    audio_capable = 0
    for m in models:
        if not m.is_active or m.known_zdr_blocked or m.circuit_state == CircuitState.OPEN:
            continue
        resolutions.update(_safe_json_list(m.supported_resolutions_json))
        aspect_ratios.update(_safe_json_list(m.supported_aspect_ratios_json))
        durations.update(_safe_json_list(m.supported_durations_json))
        if m.supports_text_to_video:
            generation_types.add("TEXT_TO_VIDEO")
        if m.supports_image_reference:
            generation_types.update(["IMAGE_TO_VIDEO", "REFERENCE_TO_VIDEO"])
        frame_images = _safe_json_list(m.supported_frame_images_json)
        if frame_images and "first_frame" in frame_images:
            generation_types.add("FIRST_FRAME")
        if frame_images and "last_frame" in frame_images:
            generation_types.add("LAST_FRAME")
        if frame_images and "first_frame" in frame_images and "last_frame" in frame_images:
            generation_types.add("FIRST_LAST_FRAME")
        if m.supports_audio:
            audio_capable += 1
    return {
        "resolutions": sorted(resolutions),
        "aspect_ratios": sorted(aspect_ratios),
        "durations": sorted(durations),
        "generation_types": sorted(generation_types),
        "audio_capable_model_count": audio_capable,
    }
