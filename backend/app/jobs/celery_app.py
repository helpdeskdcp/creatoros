"""Celery application. Task modules register themselves via
app.jobs.tasks — import that module (not this one) to get task functions."""
from celery import Celery

import app.db.models_registry  # noqa: F401
from app.core.config import get_settings

# The models_registry import above populates Base.metadata / SQLAlchemy's
# mapper registry with EVERY ORM model before any task can run. Without
# it, a worker process that happens to run a task touching one table
# (e.g. jobs, which has a real FK to users) before anything has imported
# the `User` class crashes with NoReferencedTableError at flush time --
# SQLAlchemy resolves FK target tables lazily, by name, against whatever
# has actually been imported into this process. Previously nothing in the
# worker bootstrap imported this (only alembic and the test suite did),
# so it depended on which task happened to fire first and what it
# happened to transitively import -- a real incident, not hypothetical: a
# beat task with a short interval firing before any other task had
# incidentally imported User reproduced this exact crash in production.

settings = get_settings()

celery_app = Celery(
    "creatoros",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.jobs.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_retry_delay=60,
    task_time_limit=900,
    broker_connection_retry_on_startup=True,
)

celery_app.conf.beat_schedule = {
    "youtube-sync-all-channels": {
        "task": "app.jobs.tasks.sync_all_channels",
        "schedule": 3600.0 * 6,
    },
    "trend-refresh-all-users": {
        "task": "app.jobs.tasks.refresh_all_trends",
        "schedule": 3600.0 * 12,
    },
    "temporary-media-cleanup": {
        "task": "app.jobs.tasks.temporary_media_cleanup_job",
        "schedule": 3600.0,
    },
    "daily-growth-agent": {
        "task": "app.jobs.tasks.run_daily_growth_agent",
        "schedule": 3600.0 * 24,
    },
    "poll-pending-publishing-runs": {
        "task": "app.jobs.tasks.poll_pending_publishing_runs_task",
        "schedule": 600.0,
    },
    "poll-scheduled-publishing-runs": {
        "task": "app.jobs.tasks.poll_scheduled_publishing_runs_task",
        "schedule": 60.0,
    },
    "purge-expired-ai-cache": {
        "task": "app.jobs.tasks.purge_expired_ai_cache_task",
        "schedule": 3600.0,
    },
    "measure-video-update-impact": {
        "task": "app.jobs.tasks.measure_video_update_impact_task",
        "schedule": 3600.0 * 6,
    },
    "detect-performance-anomalies": {
        "task": "app.jobs.tasks.detect_performance_anomalies_task",
        "schedule": 3600.0 * 3,
    },
    "poll-video-jobs": {
        "task": "app.jobs.tasks.poll_video_jobs_task",
        "schedule": 30.0,
    },
    "refresh-video-model-catalog": {
        "task": "app.jobs.tasks.refresh_video_model_catalog_task",
        "schedule": 1800.0,
    },
}
