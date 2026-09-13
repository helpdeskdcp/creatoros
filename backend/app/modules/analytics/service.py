"""Analytics engine + Growth OS extensions (subscriber growth, scorecard,
diagnostic). Every score here is derived from AnalyticsSnapshot/video rows
already computed by app.modules.videos.service — this module does not
recompute channel intelligence from scratch, it builds on top of it."""
import statistics
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_quality import (
    MIN_SAMPLE_SIZE_CHANNEL_BENCHMARK,
    Confidence,
    DataQuality,
    Metric,
    insufficient_data,
    real_metric,
)
from app.modules.analytics.models import AnalyticsSnapshot, GrowthAction
from app.modules.analytics.schemas import (
    GrowthBottleneck,
    GrowthDiagnosisOut,
    GrowthScorecardOut,
    SubscriberGrowthOut,
)
from app.modules.channels.models import Channel
from app.modules.retention.models import RetentionMetric
from app.modules.videos.models import Video, VideoMetricSnapshot
from app.modules.videos.service import compute_channel_intelligence


async def take_snapshot(db: AsyncSession, channel: Channel) -> AnalyticsSnapshot:
    intel = await compute_channel_intelligence(db, channel)
    now = datetime.now(UTC)

    qualities = [
        intel.total_views.quality,
        intel.average_views.quality,
        intel.engagement_rate.quality,
    ]
    overall_quality = (
        DataQuality.INSUFFICIENT_DATA
        if DataQuality.INSUFFICIENT_DATA in qualities
        else DataQuality.REAL
    )

    snapshot = AnalyticsSnapshot(
        channel_id=channel.id,
        captured_at=now,
        total_views=intel.total_views.value,
        total_subscribers=intel.subscriber_count.value,
        average_views_per_video=intel.average_views.value,
        median_views_per_video=intel.median_views.value,
        upload_frequency_per_week=intel.upload_frequency_per_week.value,
        engagement_rate=intel.engagement_rate.value,
        performance_score=_score_from_metric(intel.average_views),
        engagement_score=_score_from_metric(intel.engagement_rate, cap=10),
        retention_score=None,
        subscriber_conversion_score=None,
        data_quality=overall_quality.value,
        sample_size=intel.total_views.sample_size,
    )
    db.add(snapshot)
    await db.commit()
    await db.refresh(snapshot)
    return snapshot


def _score_from_metric(metric: Metric, cap: float = 1.0) -> float | None:
    if metric.quality == DataQuality.INSUFFICIENT_DATA or metric.value is None:
        return None
    try:
        return round(min(float(metric.value) / cap, 100.0), 1)
    except (TypeError, ValueError):
        return None


async def list_snapshots(db: AsyncSession, channel_id: uuid.UUID) -> list[AnalyticsSnapshot]:
    result = await db.scalars(
        select(AnalyticsSnapshot)
        .where(AnalyticsSnapshot.channel_id == channel_id)
        .order_by(AnalyticsSnapshot.captured_at.desc())
    )
    return list(result)


async def compute_growth_scorecard(db: AsyncSession, channel: Channel) -> GrowthScorecardOut:
    intel = await compute_channel_intelligence(db, channel)
    now = datetime.now(UTC)

    content_score = (
        real_metric(round(min(intel.average_views.value / 1000, 100), 1), intel.average_views.sample_size)
        if intel.average_views.quality != DataQuality.INSUFFICIENT_DATA
        else insufficient_data(intel.average_views.sample_size, intel.average_views.reason or "")
    )
    discovery_score = (
        real_metric(
            round(min((intel.views_velocity_7d.value or 0) / 100, 100), 1),
            intel.views_velocity_7d.sample_size,
        )
        if intel.views_velocity_7d.quality != DataQuality.INSUFFICIENT_DATA
        else insufficient_data(intel.views_velocity_7d.sample_size, intel.views_velocity_7d.reason or "")
    )

    ctr_score = await _ctr_score(db, channel.id)
    retention_score = await _retention_score(db, channel.id)

    subscriber_conversion_score = await _subscriber_conversion_score(db, channel)
    returning_viewers_score = insufficient_data(
        0,
        "Returning-viewer data requires the YouTube Analytics 'viewerType' report, "
        "which is not yet wired into the sync pipeline",
    )
    distribution_score = insufficient_data(
        0, "No distribution campaigns have been run for this channel yet"
    )
    consistency_score = (
        real_metric(
            round(min((intel.upload_frequency_per_week.value or 0) / 3 * 100, 100), 1),
            intel.upload_frequency_per_week.sample_size,
        )
        if intel.upload_frequency_per_week.quality != DataQuality.INSUFFICIENT_DATA
        else insufficient_data(
            intel.upload_frequency_per_week.sample_size, intel.upload_frequency_per_week.reason or ""
        )
    )

    computed_components = [
        c
        for c in [content_score, discovery_score, ctr_score, retention_score, consistency_score]
        if c.quality != DataQuality.INSUFFICIENT_DATA
    ]
    missing = [
        name
        for name, m in [
            ("content", content_score),
            ("discovery", discovery_score),
            ("CTR", ctr_score),
            ("retention", retention_score),
            ("subscriber conversion", subscriber_conversion_score),
            ("returning viewers", returning_viewers_score),
            ("distribution", distribution_score),
            ("consistency", consistency_score),
        ]
        if m.quality == DataQuality.INSUFFICIENT_DATA
    ]
    explanation = (
        f"{len(computed_components)}/8 growth components computed from real data. "
        + (f"Missing data for: {', '.join(missing)}." if missing else "All components computed.")
    )

    return GrowthScorecardOut(
        channel_id=channel.id,
        computed_at=now,
        content_score=content_score,
        discovery_score=discovery_score,
        ctr_score=ctr_score,
        retention_score=retention_score,
        subscriber_conversion_score=subscriber_conversion_score,
        returning_viewers_score=returning_viewers_score,
        distribution_score=distribution_score,
        consistency_score=consistency_score,
        explanation=explanation,
    )


async def _ctr_score(db: AsyncSession, channel_id: uuid.UUID) -> Metric:
    video_ids = list(await db.scalars(select(Video.id).where(Video.channel_id == channel_id)))
    if not video_ids:
        return insufficient_data(0, "No videos synced for this channel")
    rows = list(
        await db.scalars(
            select(VideoMetricSnapshot.estimated_ctr).where(
                VideoMetricSnapshot.video_id.in_(video_ids),
                VideoMetricSnapshot.estimated_ctr.is_not(None),
            )
        )
    )
    if len(rows) < MIN_SAMPLE_SIZE_CHANNEL_BENCHMARK:
        return insufficient_data(
            len(rows),
            "CTR requires authorized YouTube Analytics impressions-CTR data, not yet available",
        )
    return real_metric(round(statistics.mean(rows) * 100, 2), len(rows))


async def _retention_score(db: AsyncSession, channel_id: uuid.UUID) -> Metric:
    video_ids = list(await db.scalars(select(Video.id).where(Video.channel_id == channel_id)))
    if not video_ids:
        return insufficient_data(0, "No videos synced for this channel")
    rows = list(
        await db.scalars(
            select(RetentionMetric).where(RetentionMetric.video_id.in_(video_ids))
        )
    )
    if len(rows) < MIN_SAMPLE_SIZE_CHANNEL_BENCHMARK:
        return insufficient_data(
            len(rows), "Not enough retention_metrics computed yet for this channel"
        )
    dropoffs = [r.early_dropoff_pct for r in rows if r.early_dropoff_pct is not None]
    if not dropoffs:
        return insufficient_data(0, "No early-dropoff data recorded")
    avg_dropoff = statistics.mean(dropoffs)
    return real_metric(round(max(0.0, 100 - avg_dropoff), 1), len(dropoffs))


async def _subscriber_conversion_score(db: AsyncSession, channel: Channel) -> Metric:
    """Was previously hardcoded to INSUFFICIENT_DATA unconditionally --
    nothing ever called compute_subscriber_growth() from the scorecard.
    Scaling matches this module's existing convention (content_score,
    discovery_score): a heuristic cap, not a claim of statistical
    precision. 5% conversion (unusually strong) maps to 100."""
    growth = await compute_subscriber_growth(db, channel)
    rate = growth.subscriber_conversion_rate
    if rate.quality == DataQuality.INSUFFICIENT_DATA or rate.value is None:
        return insufficient_data(rate.sample_size, rate.reason or "")
    return real_metric(round(min(rate.value * 20, 100), 1), rate.sample_size)


async def diagnose_growth(db: AsyncSession, channel: Channel) -> GrowthDiagnosisOut:
    intel = await compute_channel_intelligence(db, channel)
    now = datetime.now(UTC)
    bottlenecks: list[GrowthBottleneck] = []

    if intel.upload_frequency_per_week.quality != DataQuality.INSUFFICIENT_DATA:
        if (intel.upload_frequency_per_week.value or 0) < 1:
            bottlenecks.append(
                GrowthBottleneck(
                    bottleneck="LOW_CONTENT_FREQUENCY",
                    evidence=(
                        f"Only {intel.upload_frequency_per_week.value} uploads/week over the "
                        "last 90 days"
                    ),
                    affected_videos=[],
                    affected_metrics=["upload_frequency_per_week"],
                    recommended_action="Increase upload cadence to at least 1 video/week; "
                    "consistency is one of the strongest discovery signals.",
                    confidence=Confidence.MEDIUM.value,
                    sample_size=intel.upload_frequency_per_week.sample_size,
                )
            )

    if (
        intel.engagement_rate.quality != DataQuality.INSUFFICIENT_DATA
        and (intel.engagement_rate.value or 0) < 1.0
    ):
        bottlenecks.append(
            GrowthBottleneck(
                bottleneck="WEAK_TOPIC_FIT",
                evidence=f"Average engagement rate is {intel.engagement_rate.value}% "
                f"across {intel.engagement_rate.sample_size} videos",
                affected_videos=[v.youtube_video_id for v in intel.weak_videos],
                affected_metrics=["engagement_rate"],
                recommended_action="Review your weakest-performing videos for topic/format "
                "mismatch against what your audience actually watches.",
                confidence=Confidence.MEDIUM.value,
                sample_size=intel.engagement_rate.sample_size,
            )
        )

    retention_metric = await _retention_score(db, channel.id)
    if retention_metric.quality != DataQuality.INSUFFICIENT_DATA and (retention_metric.value or 100) < 50:
        bottlenecks.append(
            GrowthBottleneck(
                bottleneck="LOW_RETENTION",
                evidence=f"Average retention score {retention_metric.value}/100 "
                f"across {retention_metric.sample_size} videos",
                affected_videos=[],
                affected_metrics=["retention_score"],
                recommended_action="Investigate hook and pacing on early-dropoff videos in "
                "the Retention Intelligence view.",
                confidence=Confidence.MEDIUM.value,
                sample_size=retention_metric.sample_size,
            )
        )

    note = None
    if not bottlenecks:
        note = (
            "No bottleneck could be confidently identified from the data currently synced. "
            "This may mean the channel is performing adequately on the signals we can measure, "
            "or that not enough data has been synced yet — sync more history and reconnect "
            "with OAuth for CTR/retention/subscriber-conversion analytics."
        )

    return GrowthDiagnosisOut(
        channel_id=channel.id, computed_at=now, bottlenecks=bottlenecks, note=note
    )


async def compute_subscriber_growth(db: AsyncSession, channel: Channel) -> SubscriberGrowthOut:
    """Requires authorized YouTube Analytics data (subscribersGained per
    video/day) which is only populated once a channel completes OAuth and
    channel_analytics_sync has run. Returns INSUFFICIENT_DATA honestly until
    then rather than estimating from public counters."""
    video_ids = list(await db.scalars(select(Video.id).where(Video.channel_id == channel.id)))
    rows = (
        list(
            await db.scalars(
                select(VideoMetricSnapshot).where(
                    VideoMetricSnapshot.video_id.in_(video_ids),
                    VideoMetricSnapshot.subscribers_gained.is_not(None),
                )
            )
        )
        if video_ids
        else []
    )

    if len(rows) < MIN_SAMPLE_SIZE_CHANNEL_BENCHMARK:
        reason = (
            "Subscriber growth requires authorized YouTube Analytics data "
            "(subscribersGained) — connect this channel via OAuth and run a sync"
        )
        empty = insufficient_data(len(rows), reason)
        return SubscriberGrowthOut(
            channel_id=channel.id,
            dimension="overall",
            subscriber_growth_rate=empty,
            subscriber_conversion_rate=empty,
            subscribers_per_1000_views=empty,
            returning_viewer_rate=insufficient_data(
                0, "Returning-viewer data is not yet wired into the sync pipeline"
            ),
        )

    total_subs_gained = sum(r.subscribers_gained or 0 for r in rows)
    # window_view_count (Analytics-report views for the same period this
    # subscribers_gained figure covers) -- NOT view_count, which is the
    # Data API's cumulative-lifetime total used by the separate 7-day
    # velocity calculation and would give a meaningless ratio here.
    total_views = sum(r.window_view_count or 0 for r in rows)
    per_1000 = round((total_subs_gained / total_views) * 1000, 2) if total_views else 0.0

    return SubscriberGrowthOut(
        channel_id=channel.id,
        dimension="overall",
        subscriber_growth_rate=real_metric(total_subs_gained, len(rows)),
        subscriber_conversion_rate=real_metric(
            round((total_subs_gained / total_views) * 100, 4) if total_views else 0.0, len(rows)
        ),
        subscribers_per_1000_views=real_metric(per_1000, len(rows)),
        returning_viewer_rate=insufficient_data(
            0, "Returning-viewer data is not yet wired into the sync pipeline"
        ),
    )


async def list_todays_growth_actions(db: AsyncSession, owner_user_id: uuid.UUID) -> list[GrowthAction]:
    """The 'Today's AI Growth Missions' backend: GrowthAction rows already
    exist (written by the run_daily_growth_agent Celery task) but nothing
    in the API ever exposed them -- the production audit found this
    surfaced nowhere in the app. Most recent run_date only (not literally
    calendar-today, since the daily agent may not have run in the last
    few hours yet)."""
    latest_run_date = await db.scalar(
        select(GrowthAction.run_date)
        .where(GrowthAction.owner_user_id == owner_user_id)
        .order_by(GrowthAction.run_date.desc())
        .limit(1)
    )
    if latest_run_date is None:
        return []
    result = await db.scalars(
        select(GrowthAction)
        .where(GrowthAction.owner_user_id == owner_user_id, GrowthAction.run_date == latest_run_date)
        .order_by(GrowthAction.priority)
    )
    return list(result)
