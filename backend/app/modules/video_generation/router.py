import os
import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import NotFoundError
from app.db.session import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.users.models import User
from app.modules.video_generation import service
from app.modules.video_generation.models import VideoJob
from app.modules.video_generation.schemas import CreateVideoJobRequest, VideoJobOut, VideoModelOut
from app.video.catalog import list_active_models
from app.video.models import VideoModelCatalogEntry

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
    GET /video-jobs/{id} for status."""
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
    )
    from app.jobs.tasks import submit_video_job_task

    submit_video_job_task.delay(str(job.id))
    return job


@router.get("/jobs/{job_id}", response_model=VideoJobOut)
async def get_video_job(
    job_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    job = await db.get(VideoJob, job_id)
    if not job or job.owner_user_id != user.id:
        raise NotFoundError("Video job not found")
    return job


@router.get("/jobs/{job_id}/download")
async def download_video_job_output(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    settings: Settings = Depends(_get_settings),
):
    job = await db.get(VideoJob, job_id)
    if not job or job.owner_user_id != user.id:
        raise NotFoundError("Video job not found")
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
    job = await db.get(VideoJob, job_id)
    if not job or job.owner_user_id != user.id:
        raise NotFoundError("Video job not found")
    if not job.thumbnail_url:
        raise NotFoundError("Thumbnail is not available")
    path = service.local_path_for(settings, job.thumbnail_url)
    if not path or not os.path.isfile(path):
        raise NotFoundError("Thumbnail file is not available")
    return FileResponse(path, media_type="image/jpeg", filename=f"{job.id}.jpg")
