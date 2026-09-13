"""Channel Intelligence computations. Every number here is derived from
Video/VideoMetricSnapshot rows actually stored for the channel — nothing is
guessed, and anything below the minimum sample size returns
INSUFFICIENT_DATA per the CreatorOS data-integrity rule."""
import statistics
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_quality import (
    MIN_SAMPLE_SIZE_CHANNEL_BENCHMARK,
    Metric,
    insufficient_data,
    real_metric,
)
from app.core.timeutils import ensure_aware
from app.modules.channels.models import Channel
from app.modules.videos.models import Video, VideoFormat, VideoMetricSnapshot
from app.modules.videos.schemas import ChannelIntelligence, FormatStats, ShortsVsLongForm


async def list_channel_videos(db: AsyncSession, channel_id: uuid.UUID) -> list[Video]:
    result = await db.scalars(
        select(Video).where(Video.channel_id == channel_id).order_by(Video.published_at.desc())
    )
    return list(result)


async def compute_channel_intelligence(db: AsyncSession, channel: Channel) -> ChannelIntelligence:
    videos = await list_channel_videos(db, channel.id)
    n = len(videos)

    views = [v.view_count for v in videos if v.view_count is not None]

    total_views_metric = (
        real_metric(sum(views), n) if views else insufficient_data(0, "No video view data synced yet")
    )
    subscriber_metric = (
        real_metric(channel.subscriber_count, 1, source="youtube_data_api")
        if channel.subscriber_count is not None
        else insufficient_data(0, "Channel has not been synced yet")
    )

    if len(views) >= MIN_SAMPLE_SIZE_CHANNEL_BENCHMARK:
        average_metric = real_metric(round(statistics.mean(views), 1), len(views))
        median_metric = real_metric(round(statistics.median(views), 1), len(views))
    else:
        reason = f"Need at least {MIN_SAMPLE_SIZE_CHANNEL_BENCHMARK} videos with view data (have {len(views)})"
        average_metric = insufficient_data(len(views), reason)
        median_metric = insufficient_data(len(views), reason)

    velocity_metric = await _compute_velocity(db, [v.id for v in videos])

    upload_freq_metric = _compute_upload_frequency(videos)

    engagement_metric = _compute_engagement_rate(videos)

    if n > 0:
        format_metric = real_metric(
            ShortsVsLongForm(
                shorts=_compute_format_stats([v for v in videos if v.format == VideoFormat.SHORT]),
                long_form=_compute_format_stats([v for v in videos if v.format == VideoFormat.LONG_FORM]),
            ),
            n,
        )
    else:
        format_metric = insufficient_data(0, "No videos synced yet")

    ranked = sorted((v for v in videos if v.view_count is not None), key=lambda v: v.view_count, reverse=True)
    top_videos = ranked[:5]
    weak_videos = list(reversed(ranked[-5:])) if len(ranked) >= 2 else []

    from app.modules.videos.schemas import VideoOut

    return ChannelIntelligence(
        total_views=total_views_metric,
        subscriber_count=subscriber_metric,
        average_views=average_metric,
        median_views=median_metric,
        views_velocity_7d=velocity_metric,
        upload_frequency_per_week=upload_freq_metric,
        engagement_rate=engagement_metric,
        shorts_vs_long_form=format_metric,
        top_videos=[VideoOut.model_validate(v) for v in top_videos],
        weak_videos=[VideoOut.model_validate(v) for v in weak_videos],
    )


async def _compute_velocity(db: AsyncSession, video_ids: list[uuid.UUID]) -> Metric:
    if not video_ids:
        return insufficient_data(0, "No videos to compute velocity from")

    cutoff = datetime.now(UTC) - timedelta(days=7)
    result = await db.scalars(
        select(VideoMetricSnapshot)
        .where(VideoMetricSnapshot.video_id.in_(video_ids))
        .order_by(VideoMetricSnapshot.captured_at)
    )
    snapshots = list(result)
    by_video: dict[uuid.UUID, list[VideoMetricSnapshot]] = {}
    for s in snapshots:
        by_video.setdefault(s.video_id, []).append(s)

    total_delta = 0
    contributing = 0
    for vid_snapshots in by_video.values():
        old = [s for s in vid_snapshots if ensure_aware(s.captured_at) <= cutoff]
        recent = [s for s in vid_snapshots if ensure_aware(s.captured_at) > cutoff]
        if old and recent and old[-1].view_count is not None and recent[-1].view_count is not None:
            total_delta += recent[-1].view_count - old[-1].view_count
            contributing += 1

    if contributing < MIN_SAMPLE_SIZE_CHANNEL_BENCHMARK:
        return insufficient_data(
            contributing,
            "Need at least two metric snapshots spanning 7+ days for "
            f"{MIN_SAMPLE_SIZE_CHANNEL_BENCHMARK}+ videos to compute velocity "
            "(this fills in automatically as youtube_sync runs over time)",
        )
    return real_metric(total_delta, contributing)


def _compute_upload_frequency(videos: list[Video]) -> Metric:
    dated = [v for v in videos if v.published_at is not None]
    if not dated:
        return insufficient_data(0, "No published-date data available")

    now = datetime.now(UTC)
    window_start = now - timedelta(days=90)
    recent = [v for v in dated if ensure_aware(v.published_at) >= window_start]
    if len(recent) < 2:
        return insufficient_data(len(recent), "Fewer than 2 videos published in the last 90 days")

    per_week = round(len(recent) / (90 / 7), 2)
    return real_metric(per_week, len(recent))


def _compute_format_stats(videos: list[Video]) -> FormatStats:
    """Real per-format aggregates for one format group (Shorts or
    long-form). Averages are withheld (None) below the same minimum
    sample size used everywhere else — a format with 1 video doesn't get
    a trustworthy 'average'."""
    views = [v.view_count for v in videos if v.view_count is not None]
    total_views = sum(views) if views else 0

    eligible = [v for v in videos if v.view_count and v.view_count > 0]
    has_enough = len(eligible) >= MIN_SAMPLE_SIZE_CHANNEL_BENCHMARK

    avg_views = round(statistics.mean(views), 1) if has_enough and views else None
    avg_engagement_rate = (
        round(statistics.mean([((v.like_count or 0) + (v.comment_count or 0)) / v.view_count for v in eligible]) * 100, 3)
        if has_enough
        else None
    )

    return FormatStats(
        video_count=len(videos),
        total_views=total_views,
        avg_views=avg_views,
        avg_engagement_rate=avg_engagement_rate,
        sample_size_for_averages=len(eligible),
    )


def _compute_engagement_rate(videos: list[Video]) -> Metric:
    eligible = [v for v in videos if v.view_count and v.view_count > 0]
    if len(eligible) < MIN_SAMPLE_SIZE_CHANNEL_BENCHMARK:
        return insufficient_data(
            len(eligible),
            f"Need at least {MIN_SAMPLE_SIZE_CHANNEL_BENCHMARK} videos with view counts > 0",
        )
    rates = [
        ((v.like_count or 0) + (v.comment_count or 0)) / v.view_count for v in eligible
    ]
    return real_metric(round(statistics.mean(rates) * 100, 3), len(eligible))
