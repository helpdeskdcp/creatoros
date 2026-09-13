"""Content Calendar intelligence: suggest the best day-of-week to publish
from the channel's OWN real historical performance -- never fabricated,
honestly INSUFFICIENT_DATA below the minimum comparable sample."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.data_quality import DataQuality
from app.modules.analytics import service as analytics_service
from app.modules.channels.models import Channel
from app.modules.users.models import User, UserRole
from app.modules.videos.models import Video


async def _make_user_and_channel(db_session, email: str) -> tuple[User, Channel]:
    user = User(email=email, hashed_password="x", role=UserRole.OWNER)
    db_session.add(user)
    await db_session.flush()
    channel = Channel(owner_user_id=user.id, youtube_channel_id=f"UC_{uuid.uuid4().hex[:10]}", title="Test Channel")
    db_session.add(channel)
    await db_session.commit()
    await db_session.refresh(channel)
    return user, channel


def _next_weekday(base: datetime, weekday: int) -> datetime:
    days_ahead = (weekday - base.weekday()) % 7
    return base + timedelta(days=days_ahead)


async def _add_video(db_session, channel, published_at, view_count):
    db_session.add(
        Video(
            channel_id=channel.id, youtube_video_id=f"vid_{uuid.uuid4().hex[:8]}",
            title="T", published_at=published_at, view_count=view_count,
        )
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_insufficient_data_with_too_few_videos(db_session):
    _user, channel = await _make_user_and_channel(db_session, "fewvids@example.com")
    now = datetime.now(UTC)
    for i in range(3):
        await _add_video(db_session, channel, now - timedelta(days=i), 1000)

    result = await analytics_service.analyze_publish_timing(db_session, channel)
    assert result.quality == DataQuality.INSUFFICIENT_DATA
    assert result.best_day_of_week is None


@pytest.mark.asyncio
async def test_insufficient_data_when_days_not_diverse_enough(db_session):
    _user, channel = await _make_user_and_channel(db_session, "onedays@example.com")
    monday = _next_weekday(datetime.now(UTC) - timedelta(days=60), 0)
    # All 6 videos on the same day-of-week -- only 1 qualifying day, need >=2.
    for i in range(6):
        await _add_video(db_session, channel, monday + timedelta(weeks=i), 1000 + i * 10)

    result = await analytics_service.analyze_publish_timing(db_session, channel)
    assert result.quality == DataQuality.INSUFFICIENT_DATA


@pytest.mark.asyncio
async def test_recommends_the_real_best_performing_day(db_session):
    _user, channel = await _make_user_and_channel(db_session, "bestday@example.com")
    base = datetime.now(UTC) - timedelta(days=90)
    monday = _next_weekday(base, 0)
    wednesday = _next_weekday(base, 2)

    # Wednesday videos consistently outperform Monday videos.
    for i in range(3):
        await _add_video(db_session, channel, monday + timedelta(weeks=i), 500 + i * 5)
    for i in range(3):
        await _add_video(db_session, channel, wednesday + timedelta(weeks=i), 5000 + i * 5)

    result = await analytics_service.analyze_publish_timing(db_session, channel)
    assert result.quality == DataQuality.REAL
    assert result.best_day_of_week == "Wednesday"
    assert result.best_day_median_views == pytest.approx(5005, abs=1)
    assert result.sample_size == 6


@pytest.mark.asyncio
async def test_days_with_only_one_video_are_excluded_from_comparison(db_session):
    _user, channel = await _make_user_and_channel(db_session, "onevid@example.com")
    base = datetime.now(UTC) - timedelta(days=90)
    monday = _next_weekday(base, 0)
    wednesday = _next_weekday(base, 2)
    friday = _next_weekday(base, 4)

    # Friday has a single huge outlier video -- must not be recommended
    # since it has only 1 real data point.
    for i in range(3):
        await _add_video(db_session, channel, monday + timedelta(weeks=i), 1000)
    for i in range(3):
        await _add_video(db_session, channel, wednesday + timedelta(weeks=i), 800)
    await _add_video(db_session, channel, friday, 999999)

    result = await analytics_service.analyze_publish_timing(db_session, channel)
    assert result.quality == DataQuality.REAL
    assert result.best_day_of_week == "Monday"
