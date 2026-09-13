"""Empirical-baseline Probability Engine.

A prediction answers exactly one question: "of this channel's own past
videos that were old enough to have reached this horizon, what fraction
reached this threshold?" That is the whole model -- no black box, fully
reproducible from the same data, and it honestly reports
INSUFFICIENT_DATA rather than fabricating a number when the channel
doesn't have enough comparable history yet.

Deliberately NOT a time-series/ML forecast: building one that isn't
snake-oil requires far more historical depth than a newly-tracked channel
has. An honest baseline beats a confident-looking fake.
"""
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutils import ensure_aware
from app.modules.analytics.models import AnalyticsSnapshot
from app.modules.channels.models import Channel
from app.modules.predictions.models import (
    PredictionConfidence,
    PredictionMetric,
    PredictionOutcome,
    PredictionRecord,
)
from app.modules.videos.models import Video, VideoMetricSnapshot

MIN_COMPARABLE_FOR_ANY_PREDICTION = 5
MIN_COMPARABLE_FOR_MEDIUM = 10
MIN_COMPARABLE_FOR_HIGH = 30
# How far a snapshot may be from the exact horizon timestamp and still
# count as "the value at that horizon" -- proportional to the horizon so a
# 7-day horizon isn't held to the same absolute tolerance as a 90-day one.
_TOLERANCE_FRACTION = 0.25


def _confidence_for_sample(n: int) -> PredictionConfidence:
    if n < MIN_COMPARABLE_FOR_ANY_PREDICTION:
        return PredictionConfidence.INSUFFICIENT_DATA
    if n < MIN_COMPARABLE_FOR_MEDIUM:
        return PredictionConfidence.LOW
    if n < MIN_COMPARABLE_FOR_HIGH:
        return PredictionConfidence.MEDIUM
    return PredictionConfidence.HIGH


async def _value_at_horizon(
    db: AsyncSession, video: Video, metric: PredictionMetric, horizon_days: int, now: datetime
) -> int | None:
    """Returns the metric's value at ~horizon_days after publish, from the
    snapshot closest to that timestamp within tolerance -- or None if the
    video is too young to have reached the horizon yet, or no snapshot
    exists close enough to that point to trust."""
    if video.published_at is None:
        return None
    published_at = video.published_at
    published_at = ensure_aware(published_at)
    target = published_at + timedelta(days=horizon_days)
    if now < target:
        return None  # not old enough yet -- not a data gap, just not applicable

    tolerance = timedelta(days=max(1, horizon_days * _TOLERANCE_FRACTION))
    snapshots = list(
        await db.scalars(
            select(VideoMetricSnapshot)
            .where(
                VideoMetricSnapshot.video_id == video.id,
                VideoMetricSnapshot.captured_at >= target - tolerance,
                VideoMetricSnapshot.captured_at <= target + tolerance,
            )
            .order_by(VideoMetricSnapshot.captured_at)
        )
    )
    if not snapshots:
        return None
    closest = min(snapshots, key=lambda s: abs((ensure_aware(s.captured_at) - target).total_seconds()))
    if metric is PredictionMetric.VIEWS:
        return closest.view_count
    return None  # SUBSCRIBERS is channel-level, not per-video -- see predict_subscriber_threshold


async def predict_video_threshold_probability(
    db: AsyncSession,
    channel: Channel,
    metric: PredictionMetric,
    threshold: int,
    horizon_days: int,
    exclude_video_id: uuid.UUID | None = None,
) -> PredictionRecord:
    now = datetime.now(UTC)
    videos_stmt = select(Video).where(Video.channel_id == channel.id)
    if exclude_video_id is not None:
        videos_stmt = videos_stmt.where(Video.id != exclude_video_id)
    videos = list(await db.scalars(videos_stmt))

    comparable_values: list[int] = []
    for video in videos:
        value = await _value_at_horizon(db, video, metric, horizon_days, now)
        if value is not None:
            comparable_values.append(value)

    n = len(comparable_values)
    confidence = _confidence_for_sample(n)

    if confidence is PredictionConfidence.INSUFFICIENT_DATA:
        probability_percent = None
        evidence = (
            f"Only {n} of this channel's {len(videos)} videos have a metrics snapshot "
            f"close to {horizon_days} days after publish -- at least "
            f"{MIN_COMPARABLE_FOR_ANY_PREDICTION} are needed for an honest estimate."
        )
        positive_factors = None
        negative_factors = "Insufficient historical data synced at this horizon yet."
    else:
        hits = sum(1 for v in comparable_values if v >= threshold)
        probability_percent = round(100 * hits / n)
        evidence = (
            f"{hits} of {n} comparable historical videos on this channel reached "
            f"{threshold:,} {metric.value.lower()} by day {horizon_days} after publish."
        )
        positive_factors = (
            f"{hits} comparable video(s) already reached this threshold." if hits else None
        )
        negative_factors = (
            None if hits == n else f"{n - hits} comparable video(s) did not reach this threshold."
        )

    record = PredictionRecord(
        owner_user_id=channel.owner_user_id,
        channel_id=channel.id,
        video_id=exclude_video_id,
        metric=metric,
        threshold=threshold,
        horizon_days=horizon_days,
        probability_percent=probability_percent,
        confidence=confidence,
        comparable_video_count=n,
        positive_factors=positive_factors,
        negative_factors=negative_factors,
        evidence=evidence,
        data_freshness_at=channel.last_synced_at,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def predict_subscriber_gain_probability(
    db: AsyncSession, channel: Channel, threshold: int, horizon_days: int
) -> PredictionRecord:
    """Channel-level equivalent of predict_video_threshold_probability:
    empirical probability of gaining >= threshold subscribers within
    horizon_days, from the channel's own historical AnalyticsSnapshot
    deltas -- not a per-video metric, so it can't reuse _value_at_horizon."""
    snapshots = list(
        await db.scalars(
            select(AnalyticsSnapshot)
            .where(AnalyticsSnapshot.channel_id == channel.id, AnalyticsSnapshot.total_subscribers.is_not(None))
            .order_by(AnalyticsSnapshot.captured_at)
        )
    )
    tolerance = timedelta(days=max(1, horizon_days * _TOLERANCE_FRACTION))
    target_delta = timedelta(days=horizon_days)

    deltas: list[int] = []
    for i, start in enumerate(snapshots):
        for end in snapshots[i + 1 :]:
            gap = ensure_aware(end.captured_at) - ensure_aware(start.captured_at)
            if abs(gap - target_delta) <= tolerance:
                deltas.append(end.total_subscribers - start.total_subscribers)
                break  # one comparable window per start snapshot, closest gap wins by iteration order

    n = len(deltas)
    confidence = _confidence_for_sample(n)
    if confidence is PredictionConfidence.INSUFFICIENT_DATA:
        probability_percent = None
        evidence = (
            f"Only {n} historical {horizon_days}-day windows of subscriber-count history are synced "
            f"for this channel -- at least {MIN_COMPARABLE_FOR_ANY_PREDICTION} are needed for an honest estimate."
        )
        positive_factors = None
        negative_factors = "Insufficient subscriber-history snapshots at this horizon yet."
    else:
        hits = sum(1 for d in deltas if d >= threshold)
        probability_percent = round(100 * hits / n)
        evidence = (
            f"{hits} of {n} historical {horizon_days}-day windows on this channel gained "
            f"at least {threshold:,} subscribers."
        )
        positive_factors = f"{hits} historical window(s) already met this threshold." if hits else None
        negative_factors = None if hits == n else f"{n - hits} historical window(s) did not meet this threshold."

    record = PredictionRecord(
        owner_user_id=channel.owner_user_id,
        channel_id=channel.id,
        video_id=None,
        metric=PredictionMetric.SUBSCRIBERS,
        threshold=threshold,
        horizon_days=horizon_days,
        probability_percent=probability_percent,
        confidence=confidence,
        comparable_video_count=n,
        positive_factors=positive_factors,
        negative_factors=negative_factors,
        evidence=evidence,
        data_freshness_at=channel.last_synced_at,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def record_actual_outcome(db: AsyncSession, prediction_id: uuid.UUID, actual_value: int) -> PredictionRecord:
    """Records the real observed value once the prediction's horizon has
    elapsed -- feeds get_calibration_report(). Never inferred or
    back-filled from a guess."""
    record = await db.get(PredictionRecord, prediction_id)
    if record is None:
        raise ValueError("Prediction not found")
    record.actual_value = actual_value
    record.actual_outcome = (
        PredictionOutcome.MET if actual_value >= record.threshold else PredictionOutcome.NOT_MET
    )
    record.outcome_recorded_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(record)
    return record


class CalibrationBucket:
    def __init__(self, probability_range: str, predicted_rate: float, actual_rate: float, count: int) -> None:
        self.probability_range = probability_range
        self.predicted_rate = predicted_rate
        self.actual_rate = actual_rate
        self.count = count


async def get_calibration_report(db: AsyncSession, owner_user_id: uuid.UUID) -> list[CalibrationBucket]:
    """A well-calibrated engine's predicted probability should match its
    real hit rate: predictions bucketed at "70-80%" should see the
    threshold actually met about 70-80% of the time. Only predictions with
    a recorded actual_outcome are included -- never inferred."""
    records = list(
        await db.scalars(
            select(PredictionRecord).where(
                PredictionRecord.owner_user_id == owner_user_id,
                PredictionRecord.actual_outcome.is_not(None),
                PredictionRecord.probability_percent.is_not(None),
            )
        )
    )
    buckets: dict[tuple[int, int], list[PredictionRecord]] = {}
    for r in records:
        lo = (r.probability_percent // 10) * 10
        buckets.setdefault((lo, lo + 10), []).append(r)

    report = []
    for (lo, hi), bucket_records in sorted(buckets.items()):
        met = sum(1 for r in bucket_records if r.actual_outcome is PredictionOutcome.MET)
        report.append(
            CalibrationBucket(
                probability_range=f"{lo}-{hi}%",
                predicted_rate=round(sum(r.probability_percent for r in bucket_records) / len(bucket_records), 1),
                actual_rate=round(100 * met / len(bucket_records), 1),
                count=len(bucket_records),
            )
        )
    return report
