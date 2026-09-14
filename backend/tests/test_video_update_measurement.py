"""Verified Update Engine -> real performance measurement -> Learning Loop.
Uses view VELOCITY (views/day) before vs. after the change, never the raw
cumulative view count -- a metric that only ever increases would call
every single change a "win"."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.crypto import encrypt
from app.core.errors import ConflictError
from app.modules.channels.models import Channel, SyncStatus
from app.modules.channels.providers.mock import MockYouTubeProvider
from app.modules.experiments.models import CreatorLearningSignal
from app.modules.users.models import User, UserRole
from app.modules.video_updates import service as vu
from app.modules.video_updates.models import VideoUpdateField, VideoUpdateImpact
from app.modules.videos.models import Video, VideoMetricSnapshot


async def _make_user(db_session, email: str) -> User:
    user = User(email=email, hashed_password="x", role=UserRole.OWNER)
    db_session.add(user)
    await db_session.flush()
    return user


async def _make_executed_proposal(db_session, owner_id, monkeypatch, video_id_suffix: str, observation_window_days=14):
    shared = MockYouTubeProvider()
    monkeypatch.setattr("app.modules.video_updates.service.get_youtube_provider", lambda: shared)

    channel = Channel(
        owner_user_id=owner_id, youtube_channel_id=f"UC_{uuid.uuid4().hex[:10]}", title="Test Channel",
        oauth_access_token_encrypted=encrypt("mock-access-token"),
        oauth_refresh_token_encrypted=encrypt("mock-refresh-token"),
        oauth_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        sync_status=SyncStatus.SUCCEEDED,
    )
    db_session.add(channel)
    await db_session.flush()
    video = Video(
        channel_id=channel.id, youtube_video_id=f"vid_{video_id_suffix}",
        title="Original Title", description="d",
    )
    db_session.add(video)
    await db_session.commit()
    await db_session.refresh(video)

    proposal = await vu.propose_update(
        db_session, owner_id, video.id, VideoUpdateField.TITLE, "New Title", reason="test",
    )
    proposal.observation_window_days = observation_window_days
    await db_session.commit()
    executed = await vu.approve_and_execute(db_session, proposal.id, owner_id)
    assert executed.status.value == "SUCCEEDED_VERIFIED"
    return executed, video


async def _add_snapshot(db_session, video_id, captured_at, view_count):
    db_session.add(VideoMetricSnapshot(video_id=video_id, captured_at=captured_at, view_count=view_count))
    await db_session.commit()


@pytest.mark.asyncio
async def test_measure_impact_refuses_before_observation_window_elapses(db_session, monkeypatch):
    user = await _make_user(db_session, "toosoon@example.com")
    executed, _video = await _make_executed_proposal(db_session, user.id, monkeypatch, "toosoon")
    with pytest.raises(ConflictError):
        await vu.measure_update_impact(db_session, executed.id, user.id)


@pytest.mark.asyncio
async def test_measure_impact_win_when_velocity_increases(db_session, monkeypatch):
    user = await _make_user(db_session, "win@example.com")
    executed, video = await _make_executed_proposal(db_session, user.id, monkeypatch, "win", observation_window_days=14)
    executed.executed_at = executed.executed_at - timedelta(days=15)
    await db_session.commit()
    executed_at = executed.executed_at

    await _add_snapshot(db_session, video.id, executed_at - timedelta(days=14), 1000)
    await _add_snapshot(db_session, video.id, executed_at, 1140)  # 10/day before
    await _add_snapshot(db_session, video.id, executed_at + timedelta(days=14), 1560)  # 30/day after

    measured = await vu.measure_update_impact(db_session, executed.id, user.id)
    assert measured.impact_outcome == VideoUpdateImpact.WIN
    assert measured.baseline_view_velocity == pytest.approx(10.0, abs=0.1)
    assert measured.post_view_velocity == pytest.approx(30.0, abs=0.1)

    signal = await db_session.scalar(
        select(CreatorLearningSignal).where(
            CreatorLearningSignal.owner_user_id == user.id,
            CreatorLearningSignal.signal_type == "video_metadata_update",
            CreatorLearningSignal.signal_key == "TITLE",
        )
    )
    assert signal is not None
    assert signal.wins == 1
    assert signal.losses == 0


@pytest.mark.asyncio
async def test_measure_impact_loss_when_velocity_decreases(db_session, monkeypatch):
    user = await _make_user(db_session, "loss@example.com")
    executed, video = await _make_executed_proposal(db_session, user.id, monkeypatch, "loss", observation_window_days=14)
    executed.executed_at = executed.executed_at - timedelta(days=15)
    await db_session.commit()
    executed_at = executed.executed_at

    await _add_snapshot(db_session, video.id, executed_at - timedelta(days=14), 1000)
    await _add_snapshot(db_session, video.id, executed_at, 1420)  # 30/day before
    await _add_snapshot(db_session, video.id, executed_at + timedelta(days=14), 1560)  # 10/day after

    measured = await vu.measure_update_impact(db_session, executed.id, user.id)
    assert measured.impact_outcome == VideoUpdateImpact.LOSS

    signal = await db_session.scalar(
        select(CreatorLearningSignal).where(
            CreatorLearningSignal.owner_user_id == user.id,
            CreatorLearningSignal.signal_type == "video_metadata_update",
            CreatorLearningSignal.signal_key == "TITLE",
        )
    )
    assert signal.losses == 1
    assert signal.wins == 0


@pytest.mark.asyncio
async def test_measure_impact_neutral_within_threshold(db_session, monkeypatch):
    user = await _make_user(db_session, "neutral@example.com")
    executed, video = await _make_executed_proposal(db_session, user.id, monkeypatch, "neutral", observation_window_days=14)
    executed.executed_at = executed.executed_at - timedelta(days=15)
    await db_session.commit()
    executed_at = executed.executed_at

    await _add_snapshot(db_session, video.id, executed_at - timedelta(days=14), 1000)
    await _add_snapshot(db_session, video.id, executed_at, 1140)  # 10/day
    await _add_snapshot(db_session, video.id, executed_at + timedelta(days=14), 1275)  # ~9.6/day, within 15%

    measured = await vu.measure_update_impact(db_session, executed.id, user.id)
    assert measured.impact_outcome == VideoUpdateImpact.NEUTRAL

    # Neutral outcomes must NOT feed the learning loop as a win or loss.
    signal = await db_session.scalar(
        select(CreatorLearningSignal).where(CreatorLearningSignal.signal_key == "TITLE")
    )
    assert signal is None


@pytest.mark.asyncio
async def test_measure_impact_inconclusive_without_enough_snapshots(db_session, monkeypatch):
    user = await _make_user(db_session, "inconclusive@example.com")
    executed, _video = await _make_executed_proposal(
        db_session, user.id, monkeypatch, "inconclusive", observation_window_days=14,
    )
    executed.executed_at = executed.executed_at - timedelta(days=15)
    await db_session.commit()
    # No snapshots added at all -- nothing to measure from.

    measured = await vu.measure_update_impact(db_session, executed.id, user.id)
    assert measured.impact_outcome == VideoUpdateImpact.INCONCLUSIVE
    assert measured.baseline_view_velocity is None


@pytest.mark.asyncio
async def test_cannot_measure_twice(db_session, monkeypatch):
    user = await _make_user(db_session, "twice@example.com")
    executed, video = await _make_executed_proposal(db_session, user.id, monkeypatch, "twice", observation_window_days=14)
    executed_at = executed.executed_at
    await _add_snapshot(db_session, video.id, executed_at - timedelta(days=14), 1000)
    await _add_snapshot(db_session, video.id, executed_at, 1140)
    await _add_snapshot(db_session, video.id, executed_at + timedelta(days=14), 1560)
    executed.executed_at = executed_at - timedelta(days=15)
    await db_session.commit()

    await vu.measure_update_impact(db_session, executed.id, user.id)
    with pytest.raises(ConflictError):
        await vu.measure_update_impact(db_session, executed.id, user.id)


@pytest.mark.asyncio
async def test_list_measurable_proposals_only_returns_elapsed_windows(db_session, monkeypatch):
    user = await _make_user(db_session, "listmeasure@example.com")
    ready, _ = await _make_executed_proposal(db_session, user.id, monkeypatch, "ready", observation_window_days=14)
    ready.executed_at = datetime.now(UTC) - timedelta(days=20)
    not_ready, _ = await _make_executed_proposal(db_session, user.id, monkeypatch, "notready", observation_window_days=14)
    not_ready.executed_at = datetime.now(UTC) - timedelta(days=2)
    await db_session.commit()

    candidates = await vu.list_measurable_proposals(db_session)
    candidate_ids = {c.id for c in candidates}
    assert ready.id in candidate_ids
    assert not_ready.id not in candidate_ids
