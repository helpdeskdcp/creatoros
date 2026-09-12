"""Celery application. Task modules register themselves via
app.jobs.tasks — import that module (not this one) to get task functions."""
from celery import Celery

from app.core.config import get_settings

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
}
