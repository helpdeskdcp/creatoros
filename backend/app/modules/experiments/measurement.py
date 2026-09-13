"""Automated variant measurement: pulls a variant's REAL metric value
from the video it's linked to (VideoMetricSnapshot / Video), instead of
requiring a human to manually type in a number. Manual entry
(record_variant_result) still exists for metrics YouTube's API doesn't
expose, but this is the preferred path whenever a video is linked --
"Use real historical performance," never a guess.
"""
import statistics
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.videos.models import Video, VideoMetricSnapshot


@dataclass
class MeasurementResult:
    metric_value: float | None
    sample_size: int
    quality: str  # "REAL" | "INSUFFICIENT_DATA"
    reason: str | None = None


async def measure_video_metric(db: AsyncSession, video_id: uuid.UUID, metric: str) -> MeasurementResult:
    video = await db.get(Video, video_id)
    if not video:
        return MeasurementResult(None, 0, "INSUFFICIENT_DATA", "Linked video no longer exists")

    if metric == "views":
        if video.view_count is None:
            return MeasurementResult(None, 0, "INSUFFICIENT_DATA", "Video has no synced view count yet")
        return MeasurementResult(float(video.view_count), 1, "REAL")

    snapshots = list(
        await db.scalars(select(VideoMetricSnapshot).where(VideoMetricSnapshot.video_id == video_id))
    )

    if metric == "ctr":
        values = [s.estimated_ctr for s in snapshots if s.estimated_ctr is not None]
        reason = "No CTR data synced yet -- requires authorized YouTube Analytics access"
    elif metric == "avg_view_duration":
        values = [s.average_view_duration_seconds for s in snapshots if s.average_view_duration_seconds is not None]
        reason = "No average-view-duration data synced yet -- requires authorized YouTube Analytics access"
    elif metric == "engagement_rate":
        eligible = [s for s in snapshots if s.view_count and s.view_count > 0]
        values = [((s.like_count or 0) + (s.comment_count or 0)) / s.view_count for s in eligible]
        reason = "No engagement data synced yet"
    elif metric == "subscribers_gained":
        values = [s.subscribers_gained for s in snapshots if s.subscribers_gained is not None]
        reason = "No subscriber-gain data synced yet -- requires authorized YouTube Analytics access"
    else:
        return MeasurementResult(None, 0, "INSUFFICIENT_DATA", f"Unknown metric '{metric}'")

    if not values:
        return MeasurementResult(None, 0, "INSUFFICIENT_DATA", reason)

    return MeasurementResult(round(statistics.mean(values), 6), len(values), "REAL")


# Metrics that are proportions (0-1) admit a real two-proportion
# significance test; metrics that are counts/durations don't have a
# stored variance, so they fall back to a documented lift heuristic.
PROPORTION_METRICS = {"ctr", "engagement_rate"}
