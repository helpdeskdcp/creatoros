"""Verified Update Engine: propose -> approve -> execute -> read-back
verify -> rollback, for an EXISTING published video's metadata. Uses the
deterministic MockYouTubeProvider (stateful enough to genuinely round-trip
a write + verification read, never a real network/YouTube call) --
production talks to the real YouTubeDataAPIProvider, per this codebase's
established real-vs-fake AI/ML testing convention applied here to external
APIs generally."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.crypto import encrypt
from app.core.errors import ConflictError, NotFoundError
from app.modules.channels.models import Channel, SyncStatus
from app.modules.channels.providers.mock import MockYouTubeProvider
from app.modules.video_updates import service as video_updates_service
from app.modules.video_updates.models import VideoUpdateField, VideoUpdateStatus
from app.modules.videos.models import Video
from app.modules.users.models import User, UserRole


async def _make_user(db_session, email: str) -> User:
    user = User(email=email, hashed_password="x", role=UserRole.OWNER)
    db_session.add(user)
    await db_session.flush()
    return user


async def _make_connected_channel_with_video(db_session, owner_id, youtube_video_id="vid_test_1") -> tuple[Channel, Video]:
    channel = Channel(
        owner_user_id=owner_id,
        youtube_channel_id=f"UC_{uuid.uuid4().hex[:10]}",
        title="Test Channel",
        oauth_access_token_encrypted=encrypt("mock-access-token"),
        oauth_refresh_token_encrypted=encrypt("mock-refresh-token"),
        oauth_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        sync_status=SyncStatus.SUCCEEDED,
    )
    db_session.add(channel)
    await db_session.flush()
    video = Video(
        channel_id=channel.id, youtube_video_id=youtube_video_id,
        title=f"Mock Video {youtube_video_id}", description="Mock description", tags="mock",
    )
    db_session.add(video)
    await db_session.commit()
    await db_session.refresh(channel)
    await db_session.refresh(video)
    return channel, video


@pytest.fixture(autouse=True)
def _use_mock_youtube_provider(monkeypatch):
    """One shared mock provider instance for the whole test (not a fresh
    one per get_youtube_provider() call) so update_video_metadata's write
    and the subsequent get_video_details verification read see the same
    in-memory state -- exactly what approve_and_execute does internally in
    production against the real API."""
    shared = MockYouTubeProvider()
    monkeypatch.setattr("app.modules.video_updates.service.get_youtube_provider", lambda: shared)
    return shared


@pytest.mark.asyncio
async def test_propose_captures_current_value_and_stays_pending(db_session):
    user = await _make_user(db_session, "propose@example.com")
    _channel, video = await _make_connected_channel_with_video(db_session, user.id)

    proposal = await video_updates_service.propose_update(
        db_session, user.id, video.id, VideoUpdateField.TITLE, "New Title",
        reason="AI recommendation: clearer title", evidence="topic X outperformed by 2x",
    )
    assert proposal.status == VideoUpdateStatus.PENDING_APPROVAL
    assert proposal.previous_value == video.title
    assert proposal.proposed_value == "New Title"


@pytest.mark.asyncio
async def test_propose_rejects_title_over_100_chars(db_session):
    user = await _make_user(db_session, "toolong@example.com")
    _channel, video = await _make_connected_channel_with_video(db_session, user.id)

    with pytest.raises(Exception) as exc_info:
        await video_updates_service.propose_update(
            db_session, user.id, video.id, VideoUpdateField.TITLE, "x" * 101, reason="test",
        )
    assert "100-character" in str(exc_info.value)


@pytest.mark.asyncio
async def test_approve_and_execute_succeeds_and_verifies(db_session, _use_mock_youtube_provider):
    user = await _make_user(db_session, "execute@example.com")
    _channel, video = await _make_connected_channel_with_video(db_session, user.id, youtube_video_id="vid_exec_1")

    proposal = await video_updates_service.propose_update(
        db_session, user.id, video.id, VideoUpdateField.TITLE, "Verified New Title", reason="test",
    )
    executed = await video_updates_service.approve_and_execute(db_session, proposal.id, user.id)

    assert executed.status == VideoUpdateStatus.SUCCEEDED_VERIFIED
    assert executed.verified_at is not None
    assert executed.error_message is None
    # The independent read-back genuinely reflects the new value.
    live = (await _use_mock_youtube_provider.get_video_details(["vid_exec_1"]))[0]
    assert live.title == "Verified New Title"
    # Local cache kept in sync with the confirmed live value.
    await db_session.refresh(video)
    assert video.title == "Verified New Title"


@pytest.mark.asyncio
async def test_execute_fails_verification_when_write_silently_no_ops(db_session, _use_mock_youtube_provider, monkeypatch):
    """Simulates YouTube accepting the write call but not actually applying
    it (or applying something else) -- the engine must report
    FAILED_NOT_VERIFIED, never a false SUCCEEDED_VERIFIED."""
    user = await _make_user(db_session, "noop@example.com")
    _channel, video = await _make_connected_channel_with_video(db_session, user.id, youtube_video_id="vid_noop_1")

    async def _noop_update(access_token, youtube_video_id, **kwargs):
        # Deliberately does NOT mutate the provider's internal state.
        from app.modules.channels.providers.base import VideoData
        return VideoData(
            youtube_video_id=youtube_video_id, title="unchanged", description=None,
            thumbnail_url=None, published_at=None, duration_seconds=None, category_id=None,
        )

    monkeypatch.setattr(_use_mock_youtube_provider, "update_video_metadata", _noop_update)

    proposal = await video_updates_service.propose_update(
        db_session, user.id, video.id, VideoUpdateField.TITLE, "Should Not Apply", reason="test",
    )
    executed = await video_updates_service.approve_and_execute(db_session, proposal.id, user.id)

    assert executed.status == VideoUpdateStatus.FAILED_NOT_VERIFIED
    assert "did not match" in executed.error_message
    await db_session.refresh(video)
    assert video.title != "Should Not Apply"  # local cache never updated on unverified write


@pytest.mark.asyncio
async def test_execute_fails_cleanly_when_channel_has_no_oauth_grant(db_session):
    user = await _make_user(db_session, "nooauth@example.com")
    channel = Channel(
        owner_user_id=user.id, youtube_channel_id=f"UC_{uuid.uuid4().hex[:10]}", title="No OAuth Channel",
    )
    db_session.add(channel)
    await db_session.flush()
    video = Video(channel_id=channel.id, youtube_video_id="vid_nooauth", title="T", description="D")
    db_session.add(video)
    await db_session.commit()

    proposal = await video_updates_service.propose_update(
        db_session, user.id, video.id, VideoUpdateField.TITLE, "New", reason="test",
    )
    executed = await video_updates_service.approve_and_execute(db_session, proposal.id, user.id)
    assert executed.status == VideoUpdateStatus.FAILED_NOT_VERIFIED
    assert "OAuth" in executed.error_message


@pytest.mark.asyncio
async def test_cannot_double_execute_a_proposal(db_session):
    user = await _make_user(db_session, "double@example.com")
    _channel, video = await _make_connected_channel_with_video(db_session, user.id, youtube_video_id="vid_double")

    proposal = await video_updates_service.propose_update(
        db_session, user.id, video.id, VideoUpdateField.TITLE, "Once", reason="test",
    )
    await video_updates_service.approve_and_execute(db_session, proposal.id, user.id)
    with pytest.raises(ConflictError):
        await video_updates_service.approve_and_execute(db_session, proposal.id, user.id)


@pytest.mark.asyncio
async def test_reject_prevents_execution(db_session):
    user = await _make_user(db_session, "reject@example.com")
    _channel, video = await _make_connected_channel_with_video(db_session, user.id, youtube_video_id="vid_reject")

    proposal = await video_updates_service.propose_update(
        db_session, user.id, video.id, VideoUpdateField.TITLE, "Rejected Title", reason="test",
    )
    rejected = await video_updates_service.reject_proposal(db_session, proposal.id, user.id)
    assert rejected.status == VideoUpdateStatus.REJECTED
    with pytest.raises(ConflictError):
        await video_updates_service.approve_and_execute(db_session, proposal.id, user.id)


@pytest.mark.asyncio
async def test_rollback_reverts_to_the_verified_previous_value(db_session, _use_mock_youtube_provider):
    user = await _make_user(db_session, "rollback@example.com")
    _channel, video = await _make_connected_channel_with_video(db_session, user.id, youtube_video_id="vid_rollback")
    original_title = video.title

    proposal = await video_updates_service.propose_update(
        db_session, user.id, video.id, VideoUpdateField.TITLE, "Changed Title", reason="test",
    )
    executed = await video_updates_service.approve_and_execute(db_session, proposal.id, user.id)
    assert executed.status == VideoUpdateStatus.SUCCEEDED_VERIFIED

    rollback = await video_updates_service.create_rollback(db_session, executed.id, user.id)
    assert rollback.status == VideoUpdateStatus.PENDING_APPROVAL  # rollback still needs approval
    assert rollback.proposed_value == original_title
    assert rollback.rollback_of_id == executed.id

    rolled_back = await video_updates_service.approve_and_execute(db_session, rollback.id, user.id)
    assert rolled_back.status == VideoUpdateStatus.SUCCEEDED_VERIFIED
    await db_session.refresh(video)
    assert video.title == original_title


@pytest.mark.asyncio
async def test_cannot_rollback_a_proposal_that_never_succeeded(db_session):
    user = await _make_user(db_session, "badrollback@example.com")
    _channel, video = await _make_connected_channel_with_video(db_session, user.id, youtube_video_id="vid_badrollback")

    proposal = await video_updates_service.propose_update(
        db_session, user.id, video.id, VideoUpdateField.TITLE, "Never Approved", reason="test",
    )
    with pytest.raises(ConflictError):
        await video_updates_service.create_rollback(db_session, proposal.id, user.id)


@pytest.mark.asyncio
async def test_creator_isolation_cannot_propose_update_on_another_users_video(db_session):
    owner = await _make_user(db_session, "isoowner@example.com")
    attacker = await _make_user(db_session, "isoattacker@example.com")
    _channel, video = await _make_connected_channel_with_video(db_session, owner.id, youtube_video_id="vid_iso")

    with pytest.raises(NotFoundError):
        await video_updates_service.propose_update(
            db_session, attacker.id, video.id, VideoUpdateField.TITLE, "Hijacked Title", reason="test",
        )


@pytest.mark.asyncio
async def test_creator_isolation_cannot_approve_another_users_proposal(db_session):
    owner = await _make_user(db_session, "isoowner2@example.com")
    attacker = await _make_user(db_session, "isoattacker2@example.com")
    _channel, video = await _make_connected_channel_with_video(db_session, owner.id, youtube_video_id="vid_iso2")

    proposal = await video_updates_service.propose_update(
        db_session, owner.id, video.id, VideoUpdateField.TITLE, "Owner's Change", reason="test",
    )
    with pytest.raises(NotFoundError):
        await video_updates_service.approve_and_execute(db_session, proposal.id, attacker.id)


@pytest.mark.asyncio
async def test_tags_field_round_trips_as_a_list(db_session, _use_mock_youtube_provider):
    user = await _make_user(db_session, "tags@example.com")
    _channel, video = await _make_connected_channel_with_video(db_session, user.id, youtube_video_id="vid_tags")

    proposal = await video_updates_service.propose_update(
        db_session, user.id, video.id, VideoUpdateField.TAGS, ["espresso", "coffee", "budget"], reason="test",
    )
    executed = await video_updates_service.approve_and_execute(db_session, proposal.id, user.id)
    assert executed.status == VideoUpdateStatus.SUCCEEDED_VERIFIED
    live = (await _use_mock_youtube_provider.get_video_details(["vid_tags"]))[0]
    assert live.tags == ["espresso", "coffee", "budget"]
