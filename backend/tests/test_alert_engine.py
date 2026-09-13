"""Alert Engine: performance-anomaly detection (real velocity math, never
a fabricated threshold) and notification wiring on real failure paths
(sync failure, YouTube update failure) -- production audit found these
NotificationEvent values were defined but nothing ever triggered them."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.crypto import encrypt
from app.modules.analytics import service as analytics_service
from app.modules.channels.models import Channel, SyncStatus
from app.modules.notifications.models import Notification, NotificationEvent
from app.modules.users.models import User, UserRole
from app.modules.videos.models import Video, VideoMetricSnapshot
from sqlalchemy import select


async def _make_user_and_channel(db_session, email: str, **channel_kwargs) -> tuple[User, Channel]:
    user = User(email=email, hashed_password="x", role=UserRole.OWNER)
    db_session.add(user)
    await db_session.flush()
    channel = Channel(
        owner_user_id=user.id, youtube_channel_id=f"UC_{uuid.uuid4().hex[:10]}", title="Test Channel",
        **channel_kwargs,
    )
    db_session.add(channel)
    await db_session.commit()
    await db_session.refresh(channel)
    return user, channel


async def _make_video_with_snapshots(db_session, channel, view_counts: list[int], spacing_days=1) -> Video:
    video = Video(channel_id=channel.id, youtube_video_id=f"vid_{uuid.uuid4().hex[:8]}", title="T")
    db_session.add(video)
    await db_session.flush()
    now = datetime.now(UTC)
    for i, vc in enumerate(view_counts):
        db_session.add(
            VideoMetricSnapshot(
                video_id=video.id,
                captured_at=now - timedelta(days=(len(view_counts) - 1 - i) * spacing_days),
                view_count=vc,
            )
        )
    await db_session.commit()
    await db_session.refresh(video)
    return video


@pytest.mark.asyncio
async def test_detects_acceleration(db_session):
    _user, channel = await _make_user_and_channel(db_session, "accel@example.com")
    # baseline: 10/day, recent: 50/day -> 5x
    await _make_video_with_snapshots(db_session, channel, [1000, 1010, 1060])

    anomalies = await analytics_service.detect_performance_anomalies(db_session, channel)
    assert len(anomalies) == 1
    assert anomalies[0].kind == "ACCELERATION"
    assert anomalies[0].ratio == pytest.approx(5.0, abs=0.1)


@pytest.mark.asyncio
async def test_detects_decline(db_session):
    _user, channel = await _make_user_and_channel(db_session, "decline@example.com")
    # baseline: 50/day, recent: 5/day -> 0.1x
    await _make_video_with_snapshots(db_session, channel, [1000, 1050, 1055])

    anomalies = await analytics_service.detect_performance_anomalies(db_session, channel)
    assert len(anomalies) == 1
    assert anomalies[0].kind == "DECLINE"


@pytest.mark.asyncio
async def test_no_anomaly_within_normal_range(db_session):
    _user, channel = await _make_user_and_channel(db_session, "normal@example.com")
    # baseline: 10/day, recent: 12/day -> 1.2x, well within thresholds
    await _make_video_with_snapshots(db_session, channel, [1000, 1010, 1022])

    anomalies = await analytics_service.detect_performance_anomalies(db_session, channel)
    assert anomalies == []


@pytest.mark.asyncio
async def test_no_anomaly_with_fewer_than_three_snapshots(db_session):
    _user, channel = await _make_user_and_channel(db_session, "toofew@example.com")
    await _make_video_with_snapshots(db_session, channel, [1000, 2000])  # would be a huge ratio if allowed

    anomalies = await analytics_service.detect_performance_anomalies(db_session, channel)
    assert anomalies == []


@pytest.mark.asyncio
async def test_no_anomaly_when_baseline_velocity_is_noise(db_session):
    _user, channel = await _make_user_and_channel(db_session, "noise@example.com")
    # baseline velocity 0.1/day (well under _MIN_BASELINE_VELOCITY) even
    # though the recent/baseline ratio would otherwise look enormous.
    await _make_video_with_snapshots(db_session, channel, [1000, 1001, 1050], spacing_days=10)

    anomalies = await analytics_service.detect_performance_anomalies(db_session, channel)
    assert anomalies == []


@pytest.mark.asyncio
async def test_sync_failure_sends_notification_only_on_first_failure(db_session, monkeypatch):
    from app.modules.channels import service as channels_service
    from app.modules.channels.providers.base import YouTubeProviderError

    user, channel = await _make_user_and_channel(
        db_session, "syncfail@example.com",
        oauth_access_token_encrypted=encrypt("token"),
        oauth_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    class _FailingProvider:
        async def get_channel(self, **kwargs):
            raise YouTubeProviderError("quota exceeded")

    monkeypatch.setattr(channels_service, "get_youtube_provider", lambda: _FailingProvider())

    with pytest.raises(YouTubeProviderError):
        await channels_service.sync_channel(db_session, channel.id)

    notifications = list(
        await db_session.scalars(
            select(Notification).where(
                Notification.user_id == user.id, Notification.event == NotificationEvent.SYNC_FAILURE,
            )
        )
    )
    assert len(notifications) == 1

    # Second consecutive failure on an already-FAILED channel must not spam.
    with pytest.raises(YouTubeProviderError):
        await channels_service.sync_channel(db_session, channel.id)

    notifications = list(
        await db_session.scalars(
            select(Notification).where(
                Notification.user_id == user.id, Notification.event == NotificationEvent.SYNC_FAILURE,
            )
        )
    )
    assert len(notifications) == 1  # still just one


@pytest.mark.asyncio
async def test_video_update_failure_sends_notification(db_session):
    from app.modules.video_updates import service as vu
    from app.modules.video_updates.models import VideoUpdateField

    user, channel = await _make_user_and_channel(db_session, "vufail@example.com")  # no OAuth grant
    video = Video(channel_id=channel.id, youtube_video_id="vid_vufail", title="T")
    db_session.add(video)
    await db_session.commit()
    await db_session.refresh(video)

    proposal = await vu.propose_update(
        db_session, user.id, video.id, VideoUpdateField.TITLE, "New Title", reason="test",
    )
    executed = await vu.approve_and_execute(db_session, proposal.id, user.id)
    assert executed.status.value == "FAILED_NOT_VERIFIED"

    notifications = list(
        await db_session.scalars(
            select(Notification).where(
                Notification.user_id == user.id, Notification.event == NotificationEvent.PUBLISHING_RESULT,
            )
        )
    )
    assert len(notifications) == 1
    assert "failed" in notifications[0].title.lower()
