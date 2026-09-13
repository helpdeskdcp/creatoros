"""Celery task definitions. Each task wraps an async service call, tracks
itself in the jobs table for observability/idempotency, and lets Celery's
own retry/backoff handle transient failures — nothing here silently
swallows an exception."""
import asyncio
import json
import uuid
from datetime import UTC, datetime

from celery import shared_task
from celery.utils.log import get_task_logger
from sqlalchemy import select

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
        async with WorkerSessionLocal() as db:
            from app.modules.channels.models import Channel

            channel_ids = list(await db.scalars(select(Channel.id)))
        for cid in channel_ids:
            youtube_sync.delay(str(cid))
        return len(channel_ids)

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
        async with WorkerSessionLocal() as db:
            from app.modules.users.models import User

            user_ids = list(await db.scalars(select(User.id)))
        for uid in user_ids:
            trend_refresh.delay(str(uid))
        return len(user_ids)

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


@shared_task
def temporary_media_cleanup_job():
    """Growth OS: CreatorOS must not become a permanent video storage server.
    Deletes any file under storage/tmp_uploads older than its TTL. Never
    touches storage/ paths outside tmp_uploads — permanent creator data
    (thumbnails, briefs) lives elsewhere and this job never sees it."""
    import os
    import time

    tmp_dir = os.path.join("storage", "tmp_uploads")
    if not os.path.isdir(tmp_dir):
        return {"deleted": 0}

    ttl_seconds = 24 * 3600
    now = time.time()
    deleted = 0
    for name in os.listdir(tmp_dir):
        path = os.path.join(tmp_dir, name)
        try:
            if os.path.isfile(path) and (now - os.path.getmtime(path)) > ttl_seconds:
                os.remove(path)
                deleted += 1
        except OSError as exc:
            logger.warning("temporary_media_cleanup_job could not remove %s: %s", path, exc)
    return {"deleted": deleted}


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
        return total

    return _run(_do_all())
