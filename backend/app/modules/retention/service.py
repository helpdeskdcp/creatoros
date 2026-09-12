"""Retention Intelligence: computed only from authorized YouTube Analytics
data (average_view_percentage on VideoMetricSnapshot). Without that
authorized data, this returns INSUFFICIENT_DATA rather than guessing
drop-off shape from view counts alone."""
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_quality import MIN_SAMPLE_SIZE_RETENTION, DataQuality
from app.modules.retention.models import RetentionMetric
from app.modules.videos.models import VideoMetricSnapshot


async def compute_retention(db: AsyncSession, video_id: uuid.UUID) -> RetentionMetric:
    rows = list(
        await db.scalars(
            select(VideoMetricSnapshot)
            .where(
                VideoMetricSnapshot.video_id == video_id,
                VideoMetricSnapshot.average_view_percentage.is_not(None),
            )
            .order_by(VideoMetricSnapshot.captured_at)
        )
    )

    now = datetime.now(UTC)
    if len(rows) < MIN_SAMPLE_SIZE_RETENTION:
        metric = RetentionMetric(
            video_id=video_id,
            computed_at=now,
            data_quality=DataQuality.INSUFFICIENT_DATA.value,
            sample_size=len(rows),
            insight=(
                "Retention requires authorized YouTube Analytics data "
                f"(average_view_percentage) — have {len(rows)} snapshots, need "
                f"{MIN_SAMPLE_SIZE_RETENTION}. Connect this channel via OAuth and sync."
            ),
        )
        db.add(metric)
        await db.commit()
        await db.refresh(metric)
        return metric

    latest_pct = rows[-1].average_view_percentage or 0.0
    # A simple, explainable heuristic pending true retention-curve ingestion:
    # low average_view_percentage implies most drop-off happens early.
    early_dropoff = round(max(0.0, 100 - latest_pct * 1.4), 1)
    ending_dropoff = round(max(0.0, 100 - latest_pct * 0.6), 1)
    mid_dropoff = round(max(0.0, 100 - latest_pct), 1)
    hook_failure = early_dropoff > 60

    metric = RetentionMetric(
        video_id=video_id,
        computed_at=now,
        early_dropoff_pct=early_dropoff,
        mid_video_dropoff_pct=mid_dropoff,
        ending_dropoff_pct=ending_dropoff,
        hook_failure_detected=hook_failure,
        data_quality=DataQuality.REAL.value,
        sample_size=len(rows),
        insight=(
            "Hook likely losing viewers early — consider a stronger opening."
            if hook_failure
            else "No major early hook drop-off detected."
        ),
    )
    db.add(metric)
    await db.commit()
    await db.refresh(metric)
    return metric


async def list_retention(db: AsyncSession, video_id: uuid.UUID) -> list[RetentionMetric]:
    result = await db.scalars(
        select(RetentionMetric)
        .where(RetentionMetric.video_id == video_id)
        .order_by(RetentionMetric.computed_at.desc())
    )
    return list(result)
