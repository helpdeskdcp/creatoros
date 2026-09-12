import pytest

from app.core.data_quality import DataQuality, insufficient_data, real_metric
from app.modules.analytics import service as analytics_service
from app.modules.channels.models import Channel, SyncStatus
from app.modules.users.models import User, UserRole


def test_insufficient_data_never_carries_a_value():
    metric = insufficient_data(sample_size=1, reason="not enough data")
    assert metric.quality == DataQuality.INSUFFICIENT_DATA
    assert metric.value is None
    assert metric.reason == "not enough data"


def test_real_metric_carries_its_value():
    metric = real_metric(42, sample_size=5)
    assert metric.quality == DataQuality.REAL
    assert metric.value == 42


@pytest.mark.asyncio
async def test_growth_diagnosis_returns_note_when_no_data(db_session):
    user = User(email="empty@example.com", hashed_password="x", role=UserRole.OWNER)
    db_session.add(user)
    await db_session.flush()
    channel = Channel(
        owner_user_id=user.id,
        youtube_channel_id="UC_empty",
        title="Empty Channel",
        sync_status=SyncStatus.NEVER_SYNCED,
    )
    db_session.add(channel)
    await db_session.commit()
    await db_session.refresh(channel)

    diagnosis = await analytics_service.diagnose_growth(db_session, channel)

    # No videos synced at all -> no bottleneck can be confidently claimed.
    assert diagnosis.bottlenecks == []
    assert diagnosis.note is not None


@pytest.mark.asyncio
async def test_subscriber_growth_is_insufficient_without_authorized_analytics(db_session):
    user = User(email="nosubs@example.com", hashed_password="x", role=UserRole.OWNER)
    db_session.add(user)
    await db_session.flush()
    channel = Channel(
        owner_user_id=user.id, youtube_channel_id="UC_nosubs", title="No Subs Channel"
    )
    db_session.add(channel)
    await db_session.commit()
    await db_session.refresh(channel)

    result = await analytics_service.compute_subscriber_growth(db_session, channel)

    assert result.subscriber_growth_rate.quality == DataQuality.INSUFFICIENT_DATA
    assert result.subscriber_growth_rate.value is None
    assert result.returning_viewer_rate.quality == DataQuality.INSUFFICIENT_DATA
