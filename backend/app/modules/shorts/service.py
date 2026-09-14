"""Long video -> Shorts/Reels content factory orchestration.

process_job() runs every automatic stage (validate, extract audio,
transcribe, detect moments, generate metadata) and stops at
READY_FOR_REVIEW -- rendering only happens for candidates a creator
explicitly approves (approve_candidate -> render_candidate), matching
the pipeline's own approval step.

Resumability: each stage only runs if its OWN durable output is
missing (no Transcript row yet, no ShortCandidate rows yet, ...), so a
retried/re-dispatched job skips whatever already completed instead of
redoing expensive work or creating duplicates.
"""
import json
import os
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.orchestrator import AIOrchestrator
from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError
from app.core.ffmpeg import FFmpegError, extract_audio, probe, render_vertical_clip
from app.core.logging import get_logger
from app.modules.media.models import MediaAsset, MediaPurpose
from app.modules.media.service import local_path_for, save_local_file
from app.modules.shorts.generation import generate_short_metadata
from app.modules.shorts.models import (
    ShortCandidate,
    ShortCandidateStatus,
    Transcript,
    TranscriptSegment,
    VideoJobStatus,
    VideoProcessingJob,
)
from app.modules.shorts.moment_detection import TranscriptSegmentLike, rank_candidates
from app.modules.shorts.providers import get_transcription_provider
from app.modules.shorts.providers.base import TranscriptionProviderError
from app.modules.shorts.subtitles import generate_srt

logger = get_logger("shorts.service")


class ProcessingError(Exception):
    """Raised when a pipeline stage fails for a reason that should stop
    the job (never silently continue past a failed stage)."""


async def create_job(
    db: AsyncSession, owner_user_id: uuid.UUID, source_media_asset_id: uuid.UUID, idempotency_key: str
) -> VideoProcessingJob:
    existing = await db.scalar(
        select(VideoProcessingJob).where(VideoProcessingJob.idempotency_key == idempotency_key)
    )
    if existing:
        return existing

    asset = await db.get(MediaAsset, source_media_asset_id)
    if not asset or asset.owner_user_id != owner_user_id:
        raise NotFoundError("MediaAsset not found")
    if asset.purpose != MediaPurpose.VIDEO:
        raise ConflictError("source_media_asset_id must be a VIDEO-purpose asset")

    job = VideoProcessingJob(
        owner_user_id=owner_user_id,
        source_media_asset_id=source_media_asset_id,
        idempotency_key=idempotency_key,
        status=VideoJobStatus.QUEUED,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


def _job_temp_dir(job_id: uuid.UUID) -> str:
    settings = get_settings()
    return os.path.join(settings.ffmpeg_temp_dir, str(job_id))


async def _resolve_source_path(db: AsyncSession, job: VideoProcessingJob) -> str:
    """Re-verifies ownership at use time (defense in depth, same pattern
    as publishing.execute_run) -- never trusts a path, always re-derives
    it from an ownership-checked MediaAsset."""
    asset = await db.get(MediaAsset, job.source_media_asset_id)
    if not asset or asset.owner_user_id != job.owner_user_id:
        raise ProcessingError("Source MediaAsset no longer exists or ownership changed")
    path = local_path_for(asset)
    if not path or not os.path.isfile(path):
        raise ProcessingError("Source media file is not available on local storage")
    return path


async def process_job(db: AsyncSession, job: VideoProcessingJob) -> VideoProcessingJob:
    if job.status in (VideoJobStatus.COMPLETED, VideoJobStatus.FAILED, VideoJobStatus.READY_FOR_REVIEW):
        return job  # already settled -- a retried dispatch must not redo or re-fail a finished job

    try:
        source_path = await _resolve_source_path(db, job)

        if job.source_duration_seconds is None:
            job.status = VideoJobStatus.VALIDATING
            job.progress_pct = 5
            await db.commit()
            probed = await probe(source_path)
            if not probed.has_audio:
                raise ProcessingError("Source video has no audio stream to transcribe")
            job.source_duration_seconds = probed.duration_seconds
            await db.commit()

        transcript = await db.scalar(select(Transcript).where(Transcript.job_id == job.id))
        if transcript is None:
            job.status = VideoJobStatus.EXTRACTING_AUDIO
            job.progress_pct = 20
            await db.commit()
            audio_path = os.path.join(_job_temp_dir(job.id), "audio.wav")
            await extract_audio(source_path, audio_path)

            job.status = VideoJobStatus.TRANSCRIBING
            job.progress_pct = 40
            await db.commit()
            try:
                provider = get_transcription_provider()
                result = await provider.transcribe(audio_path)
            except TranscriptionProviderError as exc:
                raise ProcessingError(f"Transcription failed: {exc}") from exc
            finally:
                if os.path.isfile(audio_path):
                    os.remove(audio_path)  # never keep extracted audio longer than needed

            transcript = Transcript(
                job_id=job.id, full_text=result.full_text, language=result.language, provider=result.provider,
            )
            db.add(transcript)
            await db.flush()
            for i, seg in enumerate(result.segments):
                db.add(
                    TranscriptSegment(
                        transcript_id=transcript.id, seq=i,
                        start_seconds=seg.start_seconds, end_seconds=seg.end_seconds, text=seg.text,
                    )
                )
            await db.commit()

        existing_candidates = list(
            await db.scalars(select(ShortCandidate).where(ShortCandidate.job_id == job.id))
        )
        if not existing_candidates:
            job.status = VideoJobStatus.DETECTING_MOMENTS
            job.progress_pct = 60
            await db.commit()

            segments = list(
                await db.scalars(
                    select(TranscriptSegment)
                    .where(TranscriptSegment.transcript_id == transcript.id)
                    .order_by(TranscriptSegment.seq)
                )
            )
            segment_likes = [
                TranscriptSegmentLike(start_seconds=s.start_seconds, end_seconds=s.end_seconds, text=s.text)
                for s in segments
            ]
            ranked = rank_candidates(segment_likes, transcript.full_text, top_k=5)

            orchestrator: AIOrchestrator | None = None
            for rank, (window, breakdown) in enumerate(ranked, start=1):
                candidate = ShortCandidate(
                    job_id=job.id, rank=rank, start_seconds=window.start_seconds, end_seconds=window.end_seconds,
                    score=breakdown.weighted_total, score_breakdown_json=json.dumps(breakdown.as_dict()),
                    transcript_excerpt=window.text, status=ShortCandidateStatus.PENDING_APPROVAL,
                )
                db.add(candidate)
                await db.flush()

                try:
                    if orchestrator is None:
                        from app.ai.dependency import get_orchestrator

                        orchestrator = get_orchestrator()
                    metadata = await generate_short_metadata(db, orchestrator, job.owner_user_id, window.text)
                    candidate.generated_title = metadata.title[:200]
                    candidate.generated_hook = metadata.hook
                    candidate.generated_description = metadata.description
                except Exception as exc:  # noqa: BLE001 -- metadata generation failure must not fail the whole job
                    logger.warning("short_metadata_generation_failed", job_id=str(job.id), rank=rank, error=str(exc))
            await db.commit()

        job.status = VideoJobStatus.READY_FOR_REVIEW
        job.progress_pct = 100
        job.error = None
        await db.commit()
        await db.refresh(job)
        return job

    except (ProcessingError, FFmpegError) as exc:
        job.status = VideoJobStatus.FAILED
        job.error = str(exc)
        await db.commit()
        logger.error("video_processing_job_failed", job_id=str(job.id), error=str(exc))
        raise


async def list_candidates(db: AsyncSession, job_id: uuid.UUID) -> list[ShortCandidate]:
    return list(
        await db.scalars(
            select(ShortCandidate).where(ShortCandidate.job_id == job_id).order_by(ShortCandidate.rank)
        )
    )


async def approve_candidate(db: AsyncSession, candidate: ShortCandidate, user_id: uuid.UUID) -> ShortCandidate:
    if candidate.status != ShortCandidateStatus.PENDING_APPROVAL:
        raise ConflictError(f"Cannot approve a candidate in status {candidate.status.value}")
    candidate.status = ShortCandidateStatus.APPROVED
    await db.commit()
    await db.refresh(candidate)
    return candidate


async def reject_candidate(db: AsyncSession, candidate: ShortCandidate, user_id: uuid.UUID) -> ShortCandidate:
    if candidate.status != ShortCandidateStatus.PENDING_APPROVAL:
        raise ConflictError(f"Cannot reject a candidate in status {candidate.status.value}")
    candidate.status = ShortCandidateStatus.REJECTED
    await db.commit()
    await db.refresh(candidate)
    return candidate


async def render_candidate(db: AsyncSession, candidate: ShortCandidate) -> ShortCandidate:
    """Only reachable for an APPROVED candidate -- rendering (and the
    real compute cost/output it produces) never happens without an
    explicit creator approval step."""
    if candidate.status != ShortCandidateStatus.APPROVED:
        raise ConflictError(f"Cannot render a candidate in status {candidate.status.value}")

    job = await db.get(VideoProcessingJob, candidate.job_id)
    if not job:
        raise ProcessingError("Parent job no longer exists")

    candidate.status = ShortCandidateStatus.RENDERING
    await db.commit()

    temp_output = os.path.join(_job_temp_dir(job.id), f"short_{candidate.id}.mp4")
    temp_srt = os.path.join(_job_temp_dir(job.id), f"short_{candidate.id}.srt")
    try:
        source_path = await _resolve_source_path(db, job)

        transcript = await db.scalar(select(Transcript).where(Transcript.job_id == job.id))
        segments = list(
            await db.scalars(
                select(TranscriptSegment)
                .where(TranscriptSegment.transcript_id == transcript.id)
                .order_by(TranscriptSegment.seq)
            )
        )
        srt_content = generate_srt(segments, candidate.start_seconds, candidate.end_seconds)
        os.makedirs(os.path.dirname(temp_srt), exist_ok=True)
        with open(temp_srt, "w") as f:
            f.write(srt_content)

        await render_vertical_clip(
            source_path, temp_output,
            start_seconds=candidate.start_seconds, end_seconds=candidate.end_seconds,
            subtitles_srt_path=temp_srt if srt_content.strip() else None,
        )

        asset = await save_local_file(
            db, job.owner_user_id, MediaPurpose.VIDEO, temp_output,
            original_filename=f"short_{candidate.rank}.mp4", content_type="video/mp4",
        )
        candidate.rendered_media_asset_id = asset.id
        candidate.status = ShortCandidateStatus.RENDERED
        candidate.rendered_at = datetime.now(UTC)
        candidate.render_error = None
        await db.commit()
        await db.refresh(candidate)
        return candidate
    except (FFmpegError, ProcessingError) as exc:
        candidate.status = ShortCandidateStatus.RENDER_FAILED
        candidate.render_error = str(exc)
        await db.commit()
        logger.error("short_candidate_render_failed", candidate_id=str(candidate.id), error=str(exc))
        raise
    finally:
        for path in (temp_output, temp_srt):
            if os.path.isfile(path):
                os.remove(path)
