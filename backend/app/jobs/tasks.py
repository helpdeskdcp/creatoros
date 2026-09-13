"""Celery task definitions. Each task wraps an async service call, tracks
itself in the jobs table for observability/idempotency, and lets Celery's
own retry/backoff handle transient failures — nothing here silently
swallows an exception."""
import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from celery import shared_task
from celery.utils.log import get_task_logger
from sqlalchemy import select

from app.core.config import get_settings
from app.jobs.db import WorkerSessionLocal
from app.jobs.models import Job, JobStatus

logger = get_task_logger(__name__)


def _run(coro):
    """Celery workers are sync; each task gets its own event loop."""
    return asyncio.run(coro)


async def _start_job(job_type: str, owner_user_id: uuid.UUID | None, idempotency_key: str | None, args: dict) -> Job:
    async with WorkerSessionLocal() as db:
        if idempotency_key:
            existing = await db.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
            if existing and existing.status in (JobStatus.SUCCEEDED, JobStatus.RUNNING):
                return existing
        job = Job(
            job_type=job_type,
            owner_user_id=owner_user_id,
            idempotency_key=idempotency_key,
            status=JobStatus.RUNNING,
            args_json=json.dumps(args, default=str),
            started_at=datetime.now(UTC),
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job


async def _finish_job(
    job_id: uuid.UUID, status: JobStatus, result: dict | None = None, error: str | None = None
) -> None:
    async with WorkerSessionLocal() as db:
        job = await db.get(Job, job_id)
        if not job:
            return
        job.status = status
        job.finished_at = datetime.now(UTC)
        if result is not None:
            job.result_json = json.dumps(result, default=str)
        if error is not None:
            job.error = error
        job.attempts += 1
        await db.commit()


@asynccontextmanager
async def _tracked_job(job_type: str):
    """Wraps a periodic/scheduled task body with Jobs-table observability
    (start/end/duration/status/error) -- production audit found this
    table had zero rows ever: _start_job/_finish_job existed but only
    youtube_sync actually called them. Every beat-scheduled task below
    now does. Yields the job's result dict for the caller to populate;
    on any exception the job is marked FAILED with the real error and
    the exception re-raises (Celery's own retry/backoff still applies)."""
    job = await _start_job(job_type, None, None, {})
    result: dict = {}
    try:
        yield result
    except Exception as exc:
        await _finish_job(job.id, JobStatus.FAILED, error=str(exc)[:2000])
        raise
    else:
        await _finish_job(job.id, JobStatus.SUCCEEDED, result=result)


@shared_task(bind=True, max_retries=5, default_retry_delay=60)
def youtube_sync(self, channel_id: str, owner_user_id: str | None = None):
    async def _do():
        job = await _start_job("youtube_sync", uuid.UUID(owner_user_id) if owner_user_id else None,
                                f"youtube_sync:{channel_id}:{datetime.now(UTC).date()}",
                                {"channel_id": channel_id})
        if job.status == JobStatus.SUCCEEDED:
            return job
        async with WorkerSessionLocal() as db:
            from app.modules.channels.service import sync_channel

            channel = await sync_channel(db, uuid.UUID(channel_id))
            await _finish_job(job.id, JobStatus.SUCCEEDED, {"videos_synced": True, "channel": str(channel.id)})
        return job

    try:
        return str(_run(_do()).id)
    except Exception as exc:  # noqa: BLE001
        logger.error("youtube_sync failed for %s: %s", channel_id, exc)
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def sync_all_channels(self):
    async def _do():
        async with _tracked_job("sync_all_channels") as result:
            async with WorkerSessionLocal() as db:
                from app.modules.channels.models import Channel

                channel_ids = list(await db.scalars(select(Channel.id)))
            for cid in channel_ids:
                youtube_sync.delay(str(cid))
            result["channels_queued"] = len(channel_ids)
        return result["channels_queued"]

    return _run(_do())


@shared_task(bind=True, max_retries=5, default_retry_delay=60)
def competitor_sync(self, competitor_id: str, owner_user_id: str | None = None):
    async def _do():
        async with WorkerSessionLocal() as db:
            from app.modules.competitors.service import sync_competitor

            await sync_competitor(db, uuid.UUID(competitor_id))

    try:
        _run(_do())
    except Exception as exc:  # noqa: BLE001
        logger.error("competitor_sync failed for %s: %s", competitor_id, exc)
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def trend_refresh(self, owner_user_id: str):
    async def _do():
        async with WorkerSessionLocal() as db:
            from app.modules.trends.service import refresh_trends

            trends = await refresh_trends(db, uuid.UUID(owner_user_id))
            return len(trends)

    try:
        return _run(_do())
    except Exception as exc:  # noqa: BLE001
        logger.error("trend_refresh failed for %s: %s", owner_user_id, exc)
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def refresh_all_trends(self):
    async def _do():
        async with _tracked_job("refresh_all_trends") as result:
            async with WorkerSessionLocal() as db:
                from app.modules.users.models import User

                user_ids = list(await db.scalars(select(User.id)))
            for uid in user_ids:
                trend_refresh.delay(str(uid))
            result["users_queued"] = len(user_ids)
        return result["users_queued"]

    return _run(_do())


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def analytics_sync(self, channel_id: str):
    async def _do():
        async with WorkerSessionLocal() as db:
            from app.modules.analytics.service import take_snapshot
            from app.modules.channels.models import Channel

            channel = await db.get(Channel, uuid.UUID(channel_id))
            if channel:
                await take_snapshot(db, channel)

    try:
        _run(_do())
    except Exception as exc:  # noqa: BLE001
        logger.error("analytics_sync failed for %s: %s", channel_id, exc)
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, max_retries=2, default_retry_delay=120)
def recommendation_refresh(self, owner_user_id: str):
    async def _do():
        async with WorkerSessionLocal() as db:
            from app.ai.orchestrator import build_orchestrator
            from app.modules.recommendations.service import generate_next_best_videos

            orchestrator = build_orchestrator()
            recs = await generate_next_best_videos(db, orchestrator, uuid.UUID(owner_user_id))
            return len(recs)

    try:
        return _run(_do())
    except Exception as exc:  # noqa: BLE001
        logger.error("recommendation_refresh failed for %s: %s", owner_user_id, exc)
        raise self.retry(exc=exc) from exc


@shared_task
def report_generation(owner_user_id: str):
    """Placeholder for the weekly-report notification pipeline: computes a
    growth scorecard per connected channel and queues a WEEKLY_REPORT
    notification. Intentionally simple — see docs/ROADMAP.md."""
    async def _do():
        async with WorkerSessionLocal() as db:
            from app.modules.channels.models import Channel
            from app.modules.notifications.models import NotificationChannel, NotificationEvent
            from app.modules.notifications.service import notify

            channels = list(
                await db.scalars(select(Channel).where(Channel.owner_user_id == uuid.UUID(owner_user_id)))
            )
            for channel in channels:
                await notify(
                    db,
                    uuid.UUID(owner_user_id),
                    NotificationEvent.WEEKLY_REPORT,
                    NotificationChannel.IN_APP,
                    f"Weekly report for {channel.title}",
                    "Your weekly channel report is ready in the Analytics tab.",
                )

    _run(_do())


def _sweep_flat_dir(tmp_dir: str, ttl_seconds: float, now: float) -> int:
    if not os.path.isdir(tmp_dir):
        return 0
    deleted = 0
    for name in os.listdir(tmp_dir):
        path = os.path.join(tmp_dir, name)
        try:
            if os.path.isfile(path) and (now - os.path.getmtime(path)) > ttl_seconds:
                os.remove(path)
                deleted += 1
        except OSError as exc:
            logger.warning("temporary_media_cleanup_job could not remove %s: %s", path, exc)
    return deleted


def _sweep_video_processing_dir(base_dir: str, ttl_seconds: float, now: float) -> int:
    """Per-job subdirectories under storage/_tmp_video_processing/<job_id>/
    hold intermediate audio/render output. Normal operation self-cleans
    these (see shorts.service's try/finally blocks); this sweep exists
    for the case a worker was hard-killed mid-stage (SIGKILL/OOM), which
    a try/finally cannot catch, and leaves the directory itself behind
    even when a normal run's files are removed one by one."""
    if not os.path.isdir(base_dir):
        return 0
    deleted = 0
    for job_dir_name in os.listdir(base_dir):
        job_dir = os.path.join(base_dir, job_dir_name)
        if not os.path.isdir(job_dir):
            continue
        try:
            newest_mtime = max(
                (os.path.getmtime(os.path.join(job_dir, f)) for f in os.listdir(job_dir)),
                default=os.path.getmtime(job_dir),
            )
            if (now - newest_mtime) > ttl_seconds:
                for f in os.listdir(job_dir):
                    os.remove(os.path.join(job_dir, f))
                    deleted += 1
                os.rmdir(job_dir)
        except OSError as exc:
            logger.warning("temporary_media_cleanup_job could not remove %s: %s", job_dir, exc)
    return deleted


@shared_task
def temporary_media_cleanup_job():
    """Growth OS: CreatorOS must not become a permanent video storage server.
    Deletes any file under storage/tmp_uploads (or a stale
    storage/_tmp_video_processing/<job_id>/ directory left behind by a
    hard-killed worker) older than its TTL. Never touches storage/ paths
    outside these two temp locations — permanent creator data
    (thumbnails, briefs, uploaded/rendered media) lives elsewhere and
    this job never sees it."""
    async def _do():
        async with _tracked_job("temporary_media_cleanup_job") as result:
            ttl_seconds = 24 * 3600
            now = time.time()
            deleted = _sweep_flat_dir(os.path.join("storage", "tmp_uploads"), ttl_seconds, now)
            deleted += _sweep_video_processing_dir(get_settings().ffmpeg_temp_dir, ttl_seconds, now)
            result["deleted"] = deleted
        return result

    return _run(_do())


@shared_task
def run_daily_growth_agent(owner_user_id: str | None = None):
    """CreatorGrowthAgent: composes existing engines' outputs into 'Today's
    Top 5 Growth Actions'. Never executes anything itself — every action is
    requires_approval=True unless a channel's PublishingRule explicitly
    authorizes AUTHORIZED_AUTONOMOUS execution (checked at execution time by
    the publishing safety gate, not here)."""
    async def _do(uid: uuid.UUID):
        async with WorkerSessionLocal() as db:
            from app.modules.analytics.models import GrowthAction
            from app.modules.analytics.service import diagnose_growth
            from app.modules.channels.models import Channel

            channels = list(await db.scalars(select(Channel).where(Channel.owner_user_id == uid)))
            actions_created = 0
            now = datetime.now(UTC)
            for channel in channels:
                diagnosis = await diagnose_growth(db, channel)
                for i, b in enumerate(diagnosis.bottlenecks[:5], start=1):
                    db.add(
                        GrowthAction(
                            owner_user_id=uid,
                            channel_id=channel.id,
                            run_date=now,
                            priority=i,
                            action_type=b.bottleneck,
                            title=f"Fix {b.bottleneck.replace('_', ' ').title()} on {channel.title}",
                            reason=b.recommended_action,
                            evidence=b.evidence,
                            confidence=b.confidence,
                            requires_approval=True,
                            execution_status="pending",
                        )
                    )
                    actions_created += 1
            await db.commit()
            return actions_created

    async def _do_all():
        async with _tracked_job("run_daily_growth_agent") as result:
            async with WorkerSessionLocal() as db:
                from app.modules.users.models import User

                user_ids = (
                    [uuid.UUID(owner_user_id)]
                    if owner_user_id
                    else list(await db.scalars(select(User.id)))
                )
            total = 0
            for uid in user_ids:
                total += await _do(uid)
            result["actions_created"] = total
        return result["actions_created"]

    return _run(_do_all())


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def execute_publishing_run(self, run_id: str):
    """Background execution path for an approved (READY) PublishingRun --
    the same execute_run() the synchronous POST /runs/{id}/execute endpoint
    calls, so an autonomous/scheduled trigger and an explicit human click
    share one real implementation instead of two. Retries only on a
    transport/provider-level failure (YouTubeProviderError); a run that
    lands in FAILED/configuration_required is a settled outcome, not
    something to retry blindly."""
    async def _do():
        async with WorkerSessionLocal() as db:
            from app.modules.channels.providers.base import YouTubeProviderError
            from app.modules.publishing.models import PublishingRun
            from app.modules.publishing.service import execute_run

            run = await db.get(PublishingRun, uuid.UUID(run_id))
            if not run:
                return {"error": "run not found"}
            try:
                run, result = await execute_run(db, run)
            except YouTubeProviderError as exc:
                raise exc
            return {"run_id": str(run.id), "result": result}

    try:
        return _run(_do())
    except Exception as exc:  # noqa: BLE001
        logger.error("execute_publishing_run failed for %s: %s", run_id, exc)
        raise self.retry(exc=exc) from exc


@shared_task
def poll_pending_publishing_runs_task():
    """Finalizes runs stuck in PROCESSING once YouTube's own processing
    completes and the video becomes publicly verifiable -- without this,
    a successful upload whose verify_publication() wasn't True on the
    first check would never transition to PUBLISHED."""
    async def _do():
        async with _tracked_job("poll_pending_publishing_runs_task") as result:
            async with WorkerSessionLocal() as db:
                from app.modules.publishing.service import poll_pending_publishing_runs

                result["value"] = await poll_pending_publishing_runs(db)
        return result["value"]

    return _run(_do())


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_video_job_task(self, job_id: str):
    """Runs every automatic content-factory stage (validate, extract
    audio, transcribe, detect moments, generate metadata) off the
    request path -- see shorts.service.process_job's own docstring for
    the resumability contract that makes retrying this safe."""
    async def _do():
        async with WorkerSessionLocal() as db:
            from app.modules.shorts.models import VideoProcessingJob
            from app.modules.shorts.service import process_job

            job = await db.get(VideoProcessingJob, uuid.UUID(job_id))
            if not job:
                return {"error": "job not found"}
            job = await process_job(db, job)
            return {"job_id": str(job.id), "status": job.status.value}

    try:
        return _run(_do())
    except Exception as exc:  # noqa: BLE001
        logger.error("process_video_job_task failed for %s: %s", job_id, exc)
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def render_short_candidate_task(self, candidate_id: str):
    """Rendering (real ffmpeg encode + upload into storage) only ever
    runs for a candidate a creator has explicitly approved -- see
    shorts.service.render_candidate's guard."""
    async def _do():
        async with WorkerSessionLocal() as db:
            from app.modules.shorts.models import ShortCandidate
            from app.modules.shorts.service import render_candidate

            candidate = await db.get(ShortCandidate, uuid.UUID(candidate_id))
            if not candidate:
                return {"error": "candidate not found"}
            candidate = await render_candidate(db, candidate)
            return {"candidate_id": str(candidate.id), "status": candidate.status.value}

    try:
        return _run(_do())
    except Exception as exc:  # noqa: BLE001
        logger.error("render_short_candidate_task failed for %s: %s", candidate_id, exc)
        raise self.retry(exc=exc) from exc


@shared_task
def poll_scheduled_publishing_runs_task():
    """Real scheduled publishing: SCHEDULED runs sit untouched until this
    finds scheduled_at <= now, atomically claims them (SCHEDULED -> READY,
    one UPDATE per row so a run can never be claimed twice even if this
    task somehow overlaps itself), and dispatches execute_publishing_run
    for each claimed run separately -- so one slow/failing upload can
    never block or delay any other creator's scheduled publish."""
    async def _do():
        async with _tracked_job("poll_scheduled_publishing_runs_task") as result:
            async with WorkerSessionLocal() as db:
                from app.modules.publishing.service import claim_due_scheduled_run_ids

                claimed = await claim_due_scheduled_run_ids(db)
            for run_id in claimed:
                execute_publishing_run.delay(str(run_id))
            result["claimed"] = len(claimed)
        return result

    return _run(_do())


@shared_task
def purge_expired_ai_cache_task():
    """AI generation cache entries carry an explicit TTL (see app/ai/cache.py)
    -- a stale row is already never served as a hit, this just reclaims the
    table space on a schedule instead of letting it grow unbounded."""
    async def _do():
        async with _tracked_job("purge_expired_ai_cache_task") as result:
            async with WorkerSessionLocal() as db:
                from app.ai.cache import purge_expired_entries

                result["deleted"] = await purge_expired_entries(db)
        return result

    return _run(_do())


@shared_task
def measure_video_update_impact_task():
    """Finds SUCCEEDED_VERIFIED video-metadata changes whose observation
    window has elapsed and measures their real view-velocity impact --
    the Learning Loop only ever ingests measured, real outcomes, never an
    assumption that a change helped."""
    async def _do():
        async with _tracked_job("measure_video_update_impact_task") as result:
            async with WorkerSessionLocal() as db:
                from app.modules.video_updates.service import list_measurable_proposals, measure_update_impact

                candidates = await list_measurable_proposals(db)
                measured, errors = 0, 0
                for proposal in candidates:
                    try:
                        await measure_update_impact(db, proposal.id, proposal.owner_user_id)
                        measured += 1
                    except Exception as exc:  # noqa: BLE001
                        logger.error("measure_video_update_impact_task failed for %s: %s", proposal.id, exc)
                        errors += 1
            result["measured"] = measured
            result["errors"] = errors
        return result

    return _run(_do())
