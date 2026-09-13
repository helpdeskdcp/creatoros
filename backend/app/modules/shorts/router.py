import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crud import get_owned_or_404
from app.db.session import get_db
from app.modules.auth.dependencies import get_current_user, require_editor
from app.modules.shorts import service
from app.modules.shorts.models import ShortCandidate, VideoProcessingJob
from app.modules.shorts.schemas import (
    CreateVideoJobRequest,
    ShortCandidateOut,
    VideoProcessingJobOut,
)
from app.modules.users.models import User

router = APIRouter()


@router.post("/jobs", response_model=VideoProcessingJobOut, status_code=201)
async def create_job(
    payload: CreateVideoJobRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    """Creates the job and enqueues background processing -- validation,
    transcription, and moment detection all happen off the request path
    (see app.jobs.tasks.process_video_job_task). Never blocks an API
    worker on video processing."""
    job = await service.create_job(db, user.id, payload.source_media_asset_id, payload.idempotency_key)
    if job.status.value == "QUEUED":
        from app.jobs.tasks import process_video_job_task

        process_video_job_task.delay(str(job.id))
    return job


@router.get("/jobs", response_model=list[VideoProcessingJobOut])
async def list_jobs(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    from sqlalchemy import select

    result = await db.scalars(
        select(VideoProcessingJob)
        .where(VideoProcessingJob.owner_user_id == user.id)
        .order_by(VideoProcessingJob.created_at.desc())
    )
    return list(result)


@router.get("/jobs/{job_id}", response_model=VideoProcessingJobOut)
async def get_job(job_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await get_owned_or_404(db, VideoProcessingJob, job_id, user.id)


@router.get("/jobs/{job_id}/candidates", response_model=list[ShortCandidateOut])
async def list_candidates(
    job_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    await get_owned_or_404(db, VideoProcessingJob, job_id, user.id)
    candidates = await service.list_candidates(db, job_id)
    return [ShortCandidateOut.from_model(c) for c in candidates]


async def _get_owned_candidate(db: AsyncSession, candidate_id: uuid.UUID, user: User) -> ShortCandidate:
    """ShortCandidate has no owner_user_id of its own -- ownership flows
    through its parent job, so get_owned_or_404's direct-column check
    doesn't apply here; this re-derives the same guarantee via a join."""
    from sqlalchemy import select

    from app.core.errors import NotFoundError

    candidate = await db.scalar(
        select(ShortCandidate)
        .join(VideoProcessingJob, VideoProcessingJob.id == ShortCandidate.job_id)
        .where(ShortCandidate.id == candidate_id, VideoProcessingJob.owner_user_id == user.id)
    )
    if not candidate:
        raise NotFoundError("ShortCandidate not found")
    return candidate


@router.post("/candidates/{candidate_id}/approve", response_model=ShortCandidateOut)
async def approve_candidate(
    candidate_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_editor)
):
    candidate = await _get_owned_candidate(db, candidate_id, user)
    candidate = await service.approve_candidate(db, candidate, user.id)
    from app.jobs.tasks import render_short_candidate_task

    render_short_candidate_task.delay(str(candidate.id))
    return ShortCandidateOut.from_model(candidate)


@router.post("/candidates/{candidate_id}/reject", response_model=ShortCandidateOut)
async def reject_candidate(
    candidate_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_editor)
):
    candidate = await _get_owned_candidate(db, candidate_id, user)
    candidate = await service.reject_candidate(db, candidate, user.id)
    return ShortCandidateOut.from_model(candidate)
