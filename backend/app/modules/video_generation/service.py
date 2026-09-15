"""Video generation pipeline orchestration: create -> select model ->
submit -> poll -> download -> QC -> store -> finalize. Never blocks the
web request -- create_video_job() only selects a model and enqueues a
Celery task; everything after that runs in app.jobs.tasks's video tasks
(submit_video_job_task, poll_video_jobs_task on a beat schedule), exactly
the same "thin task wraps an async service call" split already used for
publishing runs.
"""
import json
import os
import random
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.providers.base import (
    AIProviderError,
    AIProviderUnavailableError,
    ModelNotAvailableError,
    PrivacyPolicyViolationError,
    RateLimitedError,
)
from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError, ValidationError
from app.core.ffmpeg import FFmpegError, extract_thumbnail
from app.core.logging import get_logger
from app.core.storage import StorageError, generate_key, get_storage_backend
from app.modules.video_generation.models import (
    AIVideoJobStatus,
    VideoGenerationAttempt,
    VideoGenerationType,
    VideoJob,
    VideoPriorityMode,
)
from app.video import catalog as catalog_module
from app.video.providers.openrouter_video import OpenRouterVideoProvider
from app.video.qc import run_qc
from app.video.router import (
    NoCompatibleModelError,
    NoFreeVideoModelError,
    ResolvedSelection,
    VideoRequest,
    estimate_cost,
    select_best_model,
)

logger = get_logger("video.generation")

_MAX_RETRIES_PER_MODEL = 2
_BASE_BACKOFF_S = 30
_MAX_BACKOFF_S = 600
# Section 11/12: no job may remain silently stuck forever. A job whose
# initial Celery dispatch was lost (process crash, broker hiccup between
# the DB commit and .delay()) sits in QUEUED with nothing ever advancing
# it -- reconcile_stuck_jobs() finds these. A job whose poll endpoint has
# been erroring for longer than this is escalated rather than polled
# forever (see poll_and_progress_jobs).
_STUCK_QUEUED_TIMEOUT_S = 300  # 5 minutes
_STUCK_POLL_TIMEOUT_S = 1200  # 20 minutes
# Errors where retrying the SAME model won't help -- escalate to the next
# fallback model immediately instead of burning retry budget on it. Same
# classification policy as app.ai.orchestrator's _NON_RETRYABLE_ON_SAME_PROVIDER.
_NON_RETRYABLE_ON_SAME_MODEL = (
    AIProviderUnavailableError, ModelNotAvailableError, RateLimitedError, PrivacyPolicyViolationError,
)
# A distinct, clean, user-safe error code -- surfaced instead of a raw
# per-attempt provider message when EVERY model in the fallback chain
# failed for the SAME reason: this account's OpenRouter workspace privacy
# (Zero Data Retention) policy. Section 7/15: never expose the raw
# provider guardrail text to a caller; this is the honest, actionable
# replacement for it.
ZDR_POLICY_BLOCKED_ERROR_CODE = "ZDR_POLICY_BLOCKED"
ZDR_POLICY_BLOCKED_MESSAGE = (
    "Video generation is currently blocked by this workspace's OpenRouter "
    "privacy policy (Zero Data Retention guardrail), which rejected every "
    "compatible model. An administrator can review this at "
    "openrouter.ai/workspaces/default/guardrails."
)


def _backoff_seconds(attempt: int) -> float:
    base = min(_BASE_BACKOFF_S * (2 ** max(0, attempt - 1)), _MAX_BACKOFF_S)
    return base + random.uniform(0, base * 0.25)


async def get_owned_job(db: AsyncSession, job_id: uuid.UUID, owner_user_id: uuid.UUID) -> VideoJob:
    job = await db.get(VideoJob, job_id)
    if not job or job.owner_user_id != owner_user_id:
        raise NotFoundError("Video job not found")
    return job


_IN_FLIGHT_STATUSES = (
    AIVideoJobStatus.QUEUED, AIVideoJobStatus.SUBMITTED,
    AIVideoJobStatus.PROCESSING, AIVideoJobStatus.RETRYING,
)


async def _enforce_concurrency_limit(db: AsyncSession, owner_user_id: uuid.UUID, settings: Settings) -> None:
    in_flight = await db.scalar(
        select(func.count()).select_from(VideoJob).where(
            VideoJob.owner_user_id == owner_user_id, VideoJob.status.in_(_IN_FLIGHT_STATUSES)
        )
    )
    if (in_flight or 0) >= settings.video_max_concurrent_jobs_per_user:
        raise ValidationError(
            f"You already have {in_flight} video generation job(s) in progress "
            f"(limit: {settings.video_max_concurrent_jobs_per_user}). Wait for one to finish before starting another."
        )


async def _enforce_daily_cost_limit(
    db: AsyncSession, owner_user_id: uuid.UUID, settings: Settings, *, additional_cost: float
) -> None:
    since = datetime.now(UTC) - timedelta(hours=24)
    rows = (
        await db.scalars(
            select(VideoJob).where(VideoJob.owner_user_id == owner_user_id, VideoJob.created_at >= since)
        )
    ).all()
    spent = sum((j.cost_actual if j.cost_actual is not None else (j.cost_estimate or 0.0)) for j in rows)
    if spent + additional_cost > settings.video_daily_cost_limit_usd:
        raise ValidationError(
            f"This request (~${additional_cost:.2f}) would exceed your daily video generation limit "
            f"(${settings.video_daily_cost_limit_usd:.2f}/24h, ${spent:.2f} already used)."
        )


async def create_video_job(
    db: AsyncSession,
    owner_user_id: uuid.UUID,
    *,
    generation_type: VideoGenerationType,
    prompt: str | None,
    priority_mode: VideoPriorityMode = VideoPriorityMode.AUTO,
    duration: int | None = None,
    resolution: str | None = None,
    aspect_ratio: str | None = None,
    audio: bool = False,
    input_references: list[str] | None = None,
    allow_degraded_config: bool = True,
    allow_paid_fallback: bool = False,
) -> VideoJob:
    """Validates the request against the LIVE discovered catalog (never a
    hard-coded model list) and persists a QUEUED VideoJob with its full
    fallback chain already resolved. Raises ValidationError if genuinely
    nothing in the catalog can satisfy the request, even degraded --
    never creates a job doomed to submit an invalid configuration.

    Raises NoFreeVideoModelError (NOT wrapped as ValidationError, NOT
    caught here) when priority_mode=FREE_FIRST and allow_paid_fallback is
    False but no free video model can satisfy the request -- the router
    (app.modules.video_generation.router) catches this specifically to
    return the {"status": "NO_FREE_VIDEO_MODEL", ...} contract instead of
    a generic error envelope, and no VideoJob row is created for it (the
    hard billing guard blocks the request itself, before any job/attempt
    exists)."""
    settings = get_settings()
    if duration and duration > settings.video_max_duration_seconds:
        raise ValidationError(
            f"Requested duration {duration}s exceeds the maximum allowed ({settings.video_max_duration_seconds}s)"
        )
    await _enforce_concurrency_limit(db, owner_user_id, settings)

    catalog = await catalog_module.list_active_models(db)
    request = VideoRequest(
        generation_type=generation_type,
        duration=duration,
        resolution=resolution,
        aspect_ratio=aspect_ratio,
        audio=audio,
        priority_mode=priority_mode,
        allow_degraded_config=allow_degraded_config,
        allow_paid_fallback=allow_paid_fallback,
    )
    try:
        selection: ResolvedSelection = select_best_model(catalog, request)
    except NoFreeVideoModelError:
        raise
    except NoCompatibleModelError as exc:
        raise ValidationError(str(exc)) from exc

    primary_row = next((m for m in catalog if m.model_id == selection.primary_model_id), None)
    cost_estimate = None
    if primary_row is not None:
        vp = selection.validated_params
        cost_request = VideoRequest(
            generation_type=generation_type, duration=vp.get("duration"),
            resolution=vp.get("resolution"), aspect_ratio=vp.get("aspect_ratio"), audio=bool(vp.get("audio")),
        )
        cost_estimate = estimate_cost(primary_row, cost_request)
    await _enforce_daily_cost_limit(db, owner_user_id, settings, additional_cost=cost_estimate or 0.0)

    is_free_route = bool(primary_row is not None and primary_row.is_free)
    # Only "paid fallback used" when FREE_FIRST was requested AND paid
    # permission was explicitly granted AND the selection actually ended up
    # non-free -- distinct from a QUALITY/BALANCED/etc. job, which is also
    # "not free" but never went through the free-first-then-paid path.
    paid_fallback_used = bool(
        priority_mode == VideoPriorityMode.FREE_FIRST and allow_paid_fallback and not is_free_route
    )

    job = VideoJob(
        owner_user_id=owner_user_id,
        generation_type=generation_type,
        priority_mode=priority_mode,
        prompt=prompt,
        requested_params_json=json.dumps(
            {"duration": duration, "resolution": resolution, "aspect_ratio": aspect_ratio, "audio": audio}
        ),
        validated_params_json=json.dumps(selection.validated_params),
        input_references_json=json.dumps(input_references) if input_references else None,
        degraded_from_request=selection.degraded_from_request,
        degradation_notes_json=json.dumps(selection.notes) if selection.notes else None,
        primary_model_id=selection.primary_model_id,
        fallback_chain_json=json.dumps(selection.fallback_chain),
        selected_model_id=selection.primary_model_id,
        status=AIVideoJobStatus.QUEUED,
        cost_estimate=cost_estimate,
        is_free_route=is_free_route,
        paid_fallback_used=paid_fallback_used,
        resolution=selection.validated_params.get("resolution"),
        aspect_ratio=selection.validated_params.get("aspect_ratio"),
        duration_seconds=selection.validated_params.get("duration"),
        max_attempts=1 + len(selection.fallback_chain),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    logger.info(
        "video_job_created", job_id=str(job.id), owner_user_id=str(owner_user_id),
        primary_model=selection.primary_model_id, fallback_count=len(selection.fallback_chain),
        degraded=selection.degraded_from_request,
    )
    return job


def _build_payload(model_id: str, job: VideoJob) -> dict:
    assert job.validated_params_json is not None, "job must have a resolved validated_params_json before submission"
    params = json.loads(job.validated_params_json)
    payload: dict = {"model": model_id}
    if job.prompt:
        payload["prompt"] = job.prompt
    if params.get("duration"):
        payload["duration"] = params["duration"]
    if params.get("resolution"):
        payload["resolution"] = params["resolution"]
    if params.get("aspect_ratio"):
        payload["aspect_ratio"] = params["aspect_ratio"]
    if params.get("audio"):
        payload["generate_audio"] = True

    gen_type = job.generation_type
    if job.input_references_json:
        refs = json.loads(job.input_references_json)
        if gen_type in (VideoGenerationType.IMAGE_TO_VIDEO, VideoGenerationType.REFERENCE_TO_VIDEO):
            payload["input_references"] = [
                {"type": "image_url", "image_url": {"url": url}} for url in refs
            ]
        elif gen_type in (
            VideoGenerationType.FIRST_FRAME, VideoGenerationType.LAST_FRAME, VideoGenerationType.FIRST_LAST_FRAME
        ):
            frame_images = []
            if gen_type in (VideoGenerationType.FIRST_FRAME, VideoGenerationType.FIRST_LAST_FRAME) and len(refs) > 0:
                frame_images.append({"type": "image_url", "image_url": {"url": refs[0]}, "frame_type": "first_frame"})
            if gen_type in (VideoGenerationType.LAST_FRAME, VideoGenerationType.FIRST_LAST_FRAME) and len(refs) > 1:
                frame_images.append({"type": "image_url", "image_url": {"url": refs[1]}, "frame_type": "last_frame"})
            elif gen_type == VideoGenerationType.LAST_FRAME and len(refs) == 1:
                frame_images.append({"type": "image_url", "image_url": {"url": refs[0]}, "frame_type": "last_frame"})
            payload["frame_images"] = frame_images
    return payload


async def submit_attempt(db: AsyncSession, job: VideoJob, settings: Settings | None = None) -> None:
    """Submits `job.selected_model_id` to OpenRouter and records the
    attempt. On a same-model-retryable failure, retries the SAME model up
    to _MAX_RETRIES_PER_MODEL times (with backoff) before escalating; on a
    non-retryable failure, escalates to the next fallback model
    immediately. Never leaves the job silently stuck -- every path ends in
    SUBMITTED, RETRYING (with next_retry_at set), or FAILED."""
    settings = settings or get_settings()
    provider = OpenRouterVideoProvider(settings)
    assert job.selected_model_id is not None, "submit_attempt requires a resolved selected_model_id"
    model_id = job.selected_model_id
    same_model_attempts = len(
        (
            await db.scalars(
                select(VideoGenerationAttempt).where(
                    VideoGenerationAttempt.video_job_id == job.id, VideoGenerationAttempt.model_id == model_id
                )
            )
        ).all()
    )

    job.attempt += 1
    started_at = datetime.now(UTC)
    start = time.perf_counter()
    payload = _build_payload(model_id, job)
    try:
        result = await provider.submit_job(payload)
    except AIProviderError as exc:
        latency_ms = int((time.perf_counter() - start) * 1000)
        error_code = type(exc).__name__
        db.add(VideoGenerationAttempt(
            video_job_id=job.id, attempt_number=job.attempt, model_id=model_id, outcome="failed",
            error_code=error_code, error=str(exc), latency_ms=latency_ms,
            started_at=started_at, finished_at=datetime.now(UTC),
        ))
        logger.warning(
            "video_submission_attempt_failed", job_id=str(job.id), model=model_id,
            attempt=job.attempt, error_code=error_code, error=str(exc),
        )
        if isinstance(exc, PrivacyPolicyViolationError):
            await _record_zdr_block(db, model_id)
        else:
            await _record_catalog_outcome(db, model_id, success=False)
        can_retry_same_model = (
            same_model_attempts < _MAX_RETRIES_PER_MODEL and not isinstance(exc, _NON_RETRYABLE_ON_SAME_MODEL)
        )
        if can_retry_same_model:
            job.status = AIVideoJobStatus.RETRYING
            job.next_retry_at = datetime.now(UTC) + timedelta(seconds=_backoff_seconds(same_model_attempts + 1))
            job.error = str(exc)
            job.error_code = error_code
            await db.commit()
            return
        await _advance_to_next_model_or_fail(db, job, error_code=error_code, error_message=str(exc))
        return

    job.provider_job_id = result.provider_job_id
    job.status = AIVideoJobStatus.SUBMITTED
    job.submitted_at = datetime.now(UTC)
    job.next_retry_at = None
    db.add(VideoGenerationAttempt(
        video_job_id=job.id, attempt_number=job.attempt, model_id=model_id, outcome="submitted",
        provider_job_id=result.provider_job_id, started_at=started_at, finished_at=datetime.now(UTC),
    ))
    await db.commit()
    logger.info(
        "video_job_submitted", job_id=str(job.id), model=model_id,
        provider_job_id=result.provider_job_id, attempt=job.attempt,
    )


async def _advance_to_next_model_or_fail(
    db: AsyncSession, job: VideoJob, *, error_code: str, error_message: str
) -> None:
    chain = json.loads(job.fallback_chain_json) if job.fallback_chain_json else []
    if not chain or job.attempt >= job.max_attempts:
        job.status = AIVideoJobStatus.FAILED
        job.error = error_message
        job.error_code = error_code
        if await _all_attempts_zdr_blocked(db, job.id):
            # Every single model in the chain failed for the identical
            # privacy-policy reason -- collapse the (accurate but noisy)
            # per-attempt provider message into one clean, actionable
            # error rather than surfacing the last model's raw text.
            job.error = ZDR_POLICY_BLOCKED_MESSAGE
            job.error_code = ZDR_POLICY_BLOCKED_ERROR_CODE
        job.completed_at = datetime.now(UTC)
        await db.commit()
        logger.error(
            "video_job_failed_all_models", job_id=str(job.id), final_error=job.error, error_code=job.error_code
        )
        return

    next_model = chain.pop(0)
    job.fallback_chain_json = json.dumps(chain)
    job.selected_model_id = next_model
    job.fallback_used = True
    job.status = AIVideoJobStatus.RETRYING
    job.next_retry_at = datetime.now(UTC) + timedelta(seconds=_backoff_seconds(1))
    job.error = error_message
    job.error_code = error_code
    await db.commit()
    logger.info("video_job_escalated_to_fallback", job_id=str(job.id), next_model=next_model)


async def _record_catalog_outcome(
    db: AsyncSession, model_id: str, *, success: bool, latency_ms: int | None = None
) -> None:
    row = await db.scalar(select(catalog_module.VideoModelCatalogEntry).where(
        catalog_module.VideoModelCatalogEntry.model_id == model_id
    ))
    if row is None:
        return
    if success:
        catalog_module.record_success(row, latency_ms or 0)
    else:
        catalog_module.record_failure(row)
    await db.commit()


async def _record_zdr_block(db: AsyncSession, model_id: str) -> None:
    row = await db.scalar(select(catalog_module.VideoModelCatalogEntry).where(
        catalog_module.VideoModelCatalogEntry.model_id == model_id
    ))
    if row is None:
        return
    catalog_module.mark_zdr_blocked(row)
    await db.commit()
    logger.warning("video_model_zdr_blocked", model=model_id)


async def _all_attempts_zdr_blocked(db: AsyncSession, job_id: uuid.UUID) -> bool:
    attempts = (
        await db.scalars(
            select(VideoGenerationAttempt).where(
                VideoGenerationAttempt.video_job_id == job_id, VideoGenerationAttempt.outcome == "failed"
            )
        )
    ).all()
    return bool(attempts) and all(a.error_code == "PrivacyPolicyViolationError" for a in attempts)


async def poll_and_progress_jobs(db: AsyncSession, settings: Settings | None = None) -> dict:
    """The periodic (Celery beat) sweep: advances every job currently
    waiting on either a provider response or a scheduled retry. Never
    blocks on a single slow job -- each is handled independently and a
    failure in one never stops the sweep."""
    settings = settings or get_settings()
    now = datetime.now(UTC)
    summary = {"submitted": 0, "polled": 0, "completed": 0, "failed": 0, "retried": 0}

    due_retries = (
        await db.scalars(
            select(VideoJob).where(
                VideoJob.status == AIVideoJobStatus.RETRYING,
                (VideoJob.next_retry_at.is_(None)) | (VideoJob.next_retry_at <= now),
            )
        )
    ).all()
    for job in due_retries:
        await submit_attempt(db, job, settings)
        summary["retried"] += 1

    in_flight = (
        await db.scalars(
            select(VideoJob).where(VideoJob.status.in_([AIVideoJobStatus.SUBMITTED, AIVideoJobStatus.PROCESSING]))
        )
    ).all()
    provider = OpenRouterVideoProvider(settings)
    for job in in_flight:
        summary["polled"] += 1
        assert job.provider_job_id is not None, "a SUBMITTED/PROCESSING job must have a provider_job_id"
        assert job.selected_model_id is not None, "a SUBMITTED/PROCESSING job must have a selected_model_id"
        try:
            result = await provider.poll_job(job.provider_job_id)
        except AIProviderError as exc:
            logger.warning("video_poll_failed", job_id=str(job.id), error=str(exc))
            # A transient poll failure just waits for the next sweep --
            # but if polling has been failing for this job long enough
            # that it would otherwise sit here forever (section 12: no job
            # may remain silently stuck), escalate to the next fallback
            # model instead of continuing to retry an unreachable poll
            # endpoint indefinitely.
            reference_time = job.submitted_at or job.created_at
            if (now - reference_time).total_seconds() > _STUCK_POLL_TIMEOUT_S:
                await _advance_to_next_model_or_fail(
                    db, job, error_code=type(exc).__name__,
                    error_message=f"Polling failed repeatedly for over {_STUCK_POLL_TIMEOUT_S // 60} minutes: {exc}",
                )
                summary["failed"] += 1
            continue

        if result.status in ("pending", "in_progress"):
            job.status = AIVideoJobStatus.PROCESSING
            await db.commit()
            continue

        if result.status == "completed":
            await _finalize_completed_job(db, job, result, settings)
            summary["completed"] += 1
            continue

        # failed / cancelled / expired
        await _record_catalog_outcome(db, job.selected_model_id, success=False)
        db.add(VideoGenerationAttempt(
            video_job_id=job.id, attempt_number=job.attempt, model_id=job.selected_model_id,
            outcome="failed", provider_job_id=job.provider_job_id,
            error_code=f"provider_status_{result.status}",
            error=result.error or f"Provider reported status={result.status}",
            started_at=job.submitted_at or now, finished_at=now,
        ))
        if result.status == "expired":
            job.status = AIVideoJobStatus.EXPIRED
            job.error = result.error or "Video generation job expired"
            job.completed_at = now
            await db.commit()
            summary["failed"] += 1
            continue
        await _advance_to_next_model_or_fail(
            db, job, error_code=f"provider_status_{result.status}",
            error_message=result.error or f"Provider reported status={result.status}",
        )
        summary["failed"] += 1

    return summary


async def find_stuck_queued_job_ids(db: AsyncSession) -> list[str]:
    """Section 12's reconciliation for the specific failure mode this
    session's own live testing surfaced: a QUEUED job whose Celery
    submission task never ran (dispatch lost) sits untouched forever,
    since nothing else ever looks at QUEUED jobs. Returns ids for the
    Celery task to redispatch -- kept as a plain lookup (not a mutation)
    so it has no circular import on app.jobs.tasks, matching the existing
    claim_due_scheduled_run_ids / poll_scheduled_publishing_runs_task
    split in app.modules.publishing."""
    cutoff = datetime.now(UTC) - timedelta(seconds=_STUCK_QUEUED_TIMEOUT_S)
    stuck = (
        await db.scalars(
            select(VideoJob).where(VideoJob.status == AIVideoJobStatus.QUEUED, VideoJob.created_at < cutoff)
        )
    ).all()
    if stuck:
        logger.warning("video_jobs_stuck_in_queued", count=len(stuck), job_ids=[str(j.id) for j in stuck])
    return [str(j.id) for j in stuck]


async def _finalize_completed_job(db: AsyncSession, job: VideoJob, result, settings: Settings) -> None:
    assert job.provider_job_id is not None, "a completed job must have a provider_job_id"
    assert job.selected_model_id is not None, "a completed job must have a selected_model_id"
    assert job.validated_params_json is not None, "a completed job must have validated_params_json"
    provider = OpenRouterVideoProvider(settings)
    tmp_dir = os.path.join(settings.storage_local_path, "_tmp_video_generation")
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_video_path = os.path.join(tmp_dir, f"{job.id}.mp4")

    try:
        if result.unsigned_urls:
            await provider.download_from_url(result.unsigned_urls[0], tmp_video_path)
        else:
            await provider.download_content(job.provider_job_id, tmp_video_path)
    except AIProviderError as exc:
        logger.error("video_download_failed", job_id=str(job.id), error=str(exc))
        await _advance_to_next_model_or_fail(db, job, error_code="download_failed", error_message=str(exc))
        return

    expected_params = json.loads(job.validated_params_json)
    qc = await run_qc(
        tmp_video_path,
        expected_duration_s=expected_params.get("duration"),
        expected_resolution=expected_params.get("resolution"),
        expected_audio=bool(expected_params.get("audio")),
    )
    if not qc.passed:
        logger.warning("video_qc_failed", job_id=str(job.id), reasons=qc.reasons)
        os.remove(tmp_video_path) if os.path.isfile(tmp_video_path) else None
        await _record_catalog_outcome(db, job.selected_model_id, success=False)
        await _advance_to_next_model_or_fail(
            db, job, error_code="qc_failed", error_message="; ".join(qc.reasons)
        )
        return

    storage = get_storage_backend(settings)
    video_key = generate_key(job.owner_user_id, "generated_video", ".mp4")
    try:
        stored = await storage.save(video_key, tmp_video_path)
    except StorageError as exc:
        logger.error("video_storage_failed", job_id=str(job.id), error=str(exc))
        await _advance_to_next_model_or_fail(db, job, error_code="storage_failed", error_message=str(exc))
        return

    thumbnail_key = None
    try:
        local_video_path = storage.resolve_local_path(video_key)
        tmp_thumb_path = os.path.join(tmp_dir, f"{job.id}.jpg")
        await extract_thumbnail(local_video_path, tmp_thumb_path)
        thumbnail_key = generate_key(job.owner_user_id, "generated_video_thumb", ".jpg")
        await storage.save(thumbnail_key, tmp_thumb_path)
    except (FFmpegError, StorageError) as exc:
        logger.warning("video_thumbnail_failed", job_id=str(job.id), error=str(exc))

    latency_ms = (
        int((datetime.now(UTC) - job.submitted_at).total_seconds() * 1000) if job.submitted_at else None
    )
    await _record_catalog_outcome(db, job.selected_model_id, success=True, latency_ms=latency_ms)

    job.status = AIVideoJobStatus.COMPLETED
    job.output_url = stored.key
    job.thumbnail_url = thumbnail_key
    job.cost_actual = result.cost
    job.latency_ms = latency_ms
    job.completed_at = datetime.now(UTC)
    db.add(VideoGenerationAttempt(
        video_job_id=job.id, attempt_number=job.attempt, model_id=job.selected_model_id, outcome="succeeded",
        provider_job_id=job.provider_job_id, latency_ms=latency_ms,
        started_at=job.submitted_at or job.completed_at, finished_at=job.completed_at,
    ))
    await db.commit()
    logger.info(
        "video_job_completed", job_id=str(job.id), model=job.selected_model_id,
        fallback_used=job.fallback_used, latency_ms=latency_ms, cost=result.cost,
    )


def local_path_for(settings: Settings, key: str) -> str | None:
    storage = get_storage_backend(settings)
    try:
        path = storage.resolve_local_path(key)
    except NotImplementedError:
        return None
    return path if os.path.isfile(path) else None
