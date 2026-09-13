"""Probability Engine: empirical-baseline predictions must never fabricate
a number, must honestly report INSUFFICIENT_DATA below the minimum
comparable sample, and calibration must only ever reflect recorded real
outcomes."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.analytics.models import AnalyticsSnapshot
from app.modules.channels.models import Channel
from app.modules.predictions import service as predictions_service
from app.modules.predictions.models import PredictionConfidence, PredictionMetric, PredictionOutcome
from app.modules.users.models import User, UserRole
from app.modules.videos.models import Video, VideoMetricSnapshot


async def _make_user_and_channel(db_session, email: str) -> tuple[User, Channel]:
    user = User(email=email, hashed_password="x", role=UserRole.OWNER)
    db_session.add(user)
    await db_session.flush()
    channel = Channel(
        owner_user_id=user.id, youtube_channel_id=f"UC_{uuid.uuid4().hex[:10]}", title="Test Channel",
    )
    db_session.add(channel)
    await db_session.commit()
    await db_session.refresh(channel)
    return user, channel


async def _make_video_with_snapshot_at_day(
    db_session, channel: Channel, days_old: int, snapshot_day: int, view_count: int
) -> Video:
    now = datetime.now(UTC)
    video = Video(
        channel_id=channel.id, youtube_video_id=f"vid_{uuid.uuid4().hex[:8]}",
        title="T", published_at=now - timedelta(days=days_old),
    )
    db_session.add(video)
    await db_session.flush()
    db_session.add(
        VideoMetricSnapshot(
            video_id=video.id,
            captured_at=now - timedelta(days=days_old - snapshot_day),
            view_count=view_count,
        )
    )
    await db_session.commit()
    await db_session.refresh(video)
    return video


@pytest.mark.asyncio
async def test_insufficient_data_below_minimum_sample(db_session):
    _user, channel = await _make_user_and_channel(db_session, "insuff@example.com")
    # Only 2 comparable videos -- below MIN_COMPARABLE_FOR_ANY_PREDICTION (5).
    for _ in range(2):
        await _make_video_with_snapshot_at_day(db_session, channel, days_old=40, snapshot_day=30, view_count=20000)

    record = await predictions_service.predict_video_threshold_probability(
        db_session, channel, PredictionMetric.VIEWS, threshold=10000, horizon_days=30,
    )
    assert record.confidence == PredictionConfidence.INSUFFICIENT_DATA
    assert record.probability_percent is None
    assert "Insufficient" in record.negative_factors or record.negative_factors is None
    assert str(predictions_service.MIN_COMPARABLE_FOR_ANY_PREDICTION) in record.evidence


@pytest.mark.asyncio
async def test_computes_real_empirical_probability_with_enough_samples(db_session):
    _user, channel = await _make_user_and_channel(db_session, "enough@example.com")
    # 6 videos reach >=10000 views by day 30, 4 don't -- 60% probability.
    for _ in range(6):
        await _make_video_with_snapshot_at_day(db_session, channel, days_old=40, snapshot_day=30, view_count=15000)
    for _ in range(4):
        await _make_video_with_snapshot_at_day(db_session, channel, days_old=40, snapshot_day=30, view_count=3000)

    record = await predictions_service.predict_video_threshold_probability(
        db_session, channel, PredictionMetric.VIEWS, threshold=10000, horizon_days=30,
    )
    assert record.confidence != PredictionConfidence.INSUFFICIENT_DATA
    assert record.probability_percent == 60
    assert record.comparable_video_count == 10


@pytest.mark.asyncio
async def test_video_too_young_for_horizon_is_excluded_not_counted_as_zero(db_session):
    _user, channel = await _make_user_and_channel(db_session, "young@example.com")
    # 5 old-enough comparable videos, all reaching the threshold.
    for _ in range(5):
        await _make_video_with_snapshot_at_day(db_session, channel, days_old=40, snapshot_day=30, view_count=20000)
    # A brand-new video (published yesterday) must NOT be treated as a
    # comparable "failure" just because it hasn't reached day 30 yet.
    now = datetime.now(UTC)
    young_video = Video(
        channel_id=channel.id, youtube_video_id=f"vid_{uuid.uuid4().hex[:8]}",
        title="Too young", published_at=now - timedelta(days=1),
    )
    db_session.add(young_video)
    await db_session.commit()

    record = await predictions_service.predict_video_threshold_probability(
        db_session, channel, PredictionMetric.VIEWS, threshold=10000, horizon_days=30,
    )
    assert record.comparable_video_count == 5  # young video excluded, not counted
    assert record.probability_percent == 100


@pytest.mark.asyncio
async def test_confidence_buckets_scale_with_sample_size(db_session):
    _user, channel = await _make_user_and_channel(db_session, "buckets@example.com")
    for _ in range(7):
        await _make_video_with_snapshot_at_day(db_session, channel, days_old=40, snapshot_day=30, view_count=20000)
    record = await predictions_service.predict_video_threshold_probability(
        db_session, channel, PredictionMetric.VIEWS, threshold=10000, horizon_days=30,
    )
    assert record.confidence == PredictionConfidence.LOW  # 7 is >=5 and <10


@pytest.mark.asyncio
async def test_subscriber_prediction_insufficient_without_snapshot_history(db_session):
    _user, channel = await _make_user_and_channel(db_session, "subsinsuff@example.com")
    record = await predictions_service.predict_subscriber_gain_probability(
        db_session, channel, threshold=100, horizon_days=30,
    )
    assert record.confidence == PredictionConfidence.INSUFFICIENT_DATA
    assert record.probability_percent is None


@pytest.mark.asyncio
async def test_subscriber_prediction_computes_from_real_snapshot_deltas(db_session):
    _user, channel = await _make_user_and_channel(db_session, "subsreal@example.com")
    now = datetime.now(UTC)
    # 6 independent ~30-day windows: 4 gain >=100 subs, 2 don't.
    base_subs = 1000
    for i in range(7):
        db_session.add(
            AnalyticsSnapshot(
                channel_id=channel.id,
                captured_at=now - timedelta(days=(6 - i) * 30),
                total_subscribers=base_subs + (150 * i if i < 5 else 20 * i),
                data_quality="REAL",
            )
        )
    await db_session.commit()

    record = await predictions_service.predict_subscriber_gain_probability(
        db_session, channel, threshold=100, horizon_days=30,
    )
    assert record.confidence != PredictionConfidence.INSUFFICIENT_DATA
    assert record.probability_percent is not None
    assert 0 <= record.probability_percent <= 100


@pytest.mark.asyncio
async def test_record_actual_outcome_and_calibration_report(db_session):
    user, channel = await _make_user_and_channel(db_session, "calib@example.com")
    for _ in range(8):
        await _make_video_with_snapshot_at_day(db_session, channel, days_old=40, snapshot_day=30, view_count=20000)

    predictions = []
    for _ in range(3):
        r = await predictions_service.predict_video_threshold_probability(
            db_session, channel, PredictionMetric.VIEWS, threshold=10000, horizon_days=30,
        )
        predictions.append(r)

    await predictions_service.record_actual_outcome(db_session, predictions[0].id, actual_value=15000)
    await predictions_service.record_actual_outcome(db_session, predictions[1].id, actual_value=5000)
    await predictions_service.record_actual_outcome(db_session, predictions[2].id, actual_value=20000)

    report = await predictions_service.get_calibration_report(db_session, user.id)
    assert len(report) == 1  # all three predictions landed in the same probability bucket (100%)
    bucket = report[0]
    assert bucket.count == 3
    assert bucket.actual_rate == pytest.approx(66.7, abs=0.5)  # 2 of 3 actually met


@pytest.mark.asyncio
async def test_outcome_classification_met_vs_not_met(db_session):
    _user, channel = await _make_user_and_channel(db_session, "outcome@example.com")
    for _ in range(5):
        await _make_video_with_snapshot_at_day(db_session, channel, days_old=40, snapshot_day=30, view_count=20000)
    record = await predictions_service.predict_video_threshold_probability(
        db_session, channel, PredictionMetric.VIEWS, threshold=10000, horizon_days=30,
    )
    met = await predictions_service.record_actual_outcome(db_session, record.id, actual_value=12000)
    assert met.actual_outcome == PredictionOutcome.MET

    record2 = await predictions_service.predict_video_threshold_probability(
        db_session, channel, PredictionMetric.VIEWS, threshold=10000, horizon_days=30,
    )
    not_met = await predictions_service.record_actual_outcome(db_session, record2.id, actual_value=5000)
    assert not_met.actual_outcome == PredictionOutcome.NOT_MET


@pytest.mark.asyncio
async def test_calibration_report_excludes_predictions_without_recorded_outcome(db_session):
    user, channel = await _make_user_and_channel(db_session, "nooutcome@example.com")
    for _ in range(5):
        await _make_video_with_snapshot_at_day(db_session, channel, days_old=40, snapshot_day=30, view_count=20000)
    await predictions_service.predict_video_threshold_probability(
        db_session, channel, PredictionMetric.VIEWS, threshold=10000, horizon_days=30,
    )
    report = await predictions_service.get_calibration_report(db_session, user.id)
    assert report == []
