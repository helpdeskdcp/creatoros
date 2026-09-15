import json
import os
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError
from app.db.session import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.users.models import User
from app.modules.video_generation import service
from app.modules.video_generation.models import VideoGenerationAttempt
from app.modules.video_generation.schemas import (
    CreateVideoJobRequest,
    VideoCapabilitiesOut,
    VideoGenerationAttemptOut,
    VideoHealthOut,
    VideoJobOut,
    VideoJobRoutingOut,
    VideoModelOut,
)
from app.video.catalog import get_capabilities_summary, get_health_summary, list_active_models
from app.video.models import VideoModelCatalogEntry
from app.video.router import CostVerificationRequiredError, NoFreeVideoModelError

router = APIRouter()


def _get_settings() -> Settings:
    return get_settings()


@router.get("/models", response_model=list[VideoModelOut])
async def list_video_models(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """The live, discovered catalog -- never a hard-coded list. See
    app.jobs.tasks.refresh_video_model_catalog_task for how this stays
    current without a deployment."""
    return await list_active_models(db)


@router.get("/models/all", response_model=list[VideoModelOut])
async def list_all_video_models(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Includes inactive (delisted) models -- for the admin dashboard's
    "unavailable models" view."""
    rows = (await db.scalars(select(VideoModelCatalogEntry))).all()
    return list(rows)


@router.post("/jobs", response_model=VideoJobOut, status_code=202)
async def create_video_job(
    payload: CreateVideoJobRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(_get_settings),
):
    """Selects the best available model + full fallback chain via
    VideoModelRouter and enqueues the first submission attempt. Returns
    immediately (202) -- generation itself happens asynchronously; poll
    GET /video-jobs/{id} for status.

    FREE_FIRST hard billing guard: if no genuinely free video-generation
    model can satisfy this request and the caller did not set
    allow_paid_fallback=true, NO VideoJob row is created and this returns
    the structured {"status": "NO_FREE_VIDEO_MODEL", "requires_credits":
    true, "paid_fallback_used": false} contract instead -- never a silent
    substitution of a paid model. See app.video.router.NoFreeVideoModelError."""
    try:
        job = await service.create_video_job(
            db, user.id,
            generation_type=payload.generation_type,
            prompt=payload.prompt,
            priority_mode=payload.priority_mode,
            duration=payload.duration,
            resolution=payload.resolution,
            aspect_ratio=payload.aspect_ratio,
            audio=payload.audio,
            input_references=payload.input_image_urls,
            allow_degraded_config=payload.allow_degraded_config,
            allow_paid_fallback=payload.allow_paid_fallback,
        )
    except NoFreeVideoModelError:
        return JSONResponse(
            status_code=200,
            content={"status": "NO_FREE_VIDEO_MODEL", "requires_credits": True, "paid_fallback_used": False},
        )
    except CostVerificationRequiredError as exc:
        # A model (e.g. a configured NVIDIA endpoint) could otherwise
        # satisfy this request, but this codebase has no confirmed
        # free/paid signal for it -- never auto-submit against an unknown
        # price. See app.video.router.CostVerificationRequiredError.
        return JSONResponse(
            status_code=200,
            content={"status": "COST_VERIFICATION_REQUIRED", "requires_credits": None, "detail": str(exc)},
        )

    from app.jobs.tasks import submit_video_job_task

    submit_video_job_task.delay(str(job.id))
    return job


@router.get("/jobs/{job_id}", response_model=VideoJobOut)
async def get_video_job(
    job_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    job = await service.get_owned_job(db, job_id, user.id)
    return job


@router.get("/jobs/{job_id}/download")
async def download_video_job_output(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(_get_settings),
):
    job = await service.get_owned_job(db, job_id, user.id)
    if not job.output_url:
        raise NotFoundError("Video output is not available yet")
    path = service.local_path_for(settings, job.output_url)
    if not path or not os.path.isfile(path):
        raise NotFoundError("Video output file is not available")
    return FileResponse(path, media_type="video/mp4", filename=f"{job.id}.mp4")


@router.get("/jobs/{job_id}/thumbnail")
async def download_video_job_thumbnail(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(_get_settings),
):
    job = await service.get_owned_job(db, job_id, user.id)
    if not job.thumbnail_url:
        raise NotFoundError("Thumbnail is not available")
    path = service.local_path_for(settings, job.thumbnail_url)
    if not path or not os.path.isfile(path):
        raise NotFoundError("Thumbnail file is not available")
    return FileResponse(path, media_type="image/jpeg", filename=f"{job.id}.jpg")


@router.get("/jobs/{job_id}/attempts", response_model=list[VideoGenerationAttemptOut])
async def list_video_job_attempts(
    job_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """Section 24: every attempt in this job's fallback/retry chain, one
    real row each -- ownership-checked like every other job access."""
    job = await service.get_owned_job(db, job_id, user.id)
    attempts = (
        await db.scalars(
            select(VideoGenerationAttempt)
            .where(VideoGenerationAttempt.video_job_id == job.id)
            .order_by(VideoGenerationAttempt.attempt_number)
        )
    ).all()
    return list(attempts)


@router.get("/jobs/{job_id}/routing", response_model=VideoJobRoutingOut)
async def get_video_job_routing(
    job_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """Section 6: what the router decided for this job and why -- primary
    model, remaining fallback chain, whether the request was degraded and
    to what, without ever exposing raw provider secrets/internals."""
    job = await service.get_owned_job(db, job_id, user.id)
    return VideoJobRoutingOut(
        routing_mode=job.priority_mode,
        primary_model_id=job.primary_model_id,
        remaining_fallback_chain=json.loads(job.fallback_chain_json) if job.fallback_chain_json else [],
        selected_model_id=job.selected_model_id,
        current_attempt=job.attempt,
        max_attempts=job.max_attempts,
        fallback_used=job.fallback_used,
        degraded_from_request=job.degraded_from_request,
        degradation_notes=json.loads(job.degradation_notes_json) if job.degradation_notes_json else [],
    )


@router.get("/capabilities", response_model=VideoCapabilitiesOut)
async def get_video_capabilities(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """What's actually possible right now, aggregated from the live
    catalog -- lets a caller build a request form without a hard-coded
    list that drifts from reality."""
    catalog = await list_active_models(db)
    return get_capabilities_summary(catalog)


@router.get("/health", response_model=VideoHealthOut)
async def get_video_health(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Section 18/22: real counts of active/inactive/free/ZDR-blocked
    models and circuit-breaker states -- the same data the admin dashboard
    would show, exposed as its own endpoint."""
    return await get_health_summary(db)
