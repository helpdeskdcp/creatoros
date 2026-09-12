import pytest

from app.jobs import kill_switch
from app.modules.channels.models import Channel, SyncStatus
from app.modules.publishing import service as publishing_service
from app.modules.publishing.models import PublishingMode
from app.modules.users.models import User, UserRole


async def _make_user_and_channel(db_session, oauth: bool = True):
    user = User(email="creator@example.com", hashed_password="x", role=UserRole.OWNER)
    db_session.add(user)
    await db_session.flush()

    channel = Channel(
        owner_user_id=user.id,
        youtube_channel_id="UC123",
        title="Test Channel",
        sync_status=SyncStatus.SUCCEEDED,
        oauth_access_token_encrypted="encrypted-token" if oauth else None,
    )
    db_session.add(channel)
    await db_session.commit()
    await db_session.refresh(user)
    await db_session.refresh(channel)
    return user, channel


@pytest.mark.asyncio
async def test_gate_blocks_when_oauth_missing(db_session):
    user, channel = await _make_user_and_channel(db_session, oauth=False)
    run = await publishing_service.create_run(
        db_session, user.id, channel.id, None, PublishingMode.ASSIST,
        {"title": "A video", "description": "desc"}, "idem-1",
    )
    passed, checks, reason = await publishing_service.run_safety_gate(db_session, run)
    assert not passed
    assert "oauth_token_present" in reason


@pytest.mark.asyncio
async def test_gate_blocks_autonomous_mode_when_not_enabled(db_session):
    user, channel = await _make_user_and_channel(db_session)
    run = await publishing_service.create_run(
        db_session, user.id, channel.id, None, PublishingMode.AUTHORIZED_AUTONOMOUS,
        {"title": "A video", "description": "desc", "thumbnail_path": "x.jpg"}, "idem-2",
    )
    passed, checks, reason = await publishing_service.run_safety_gate(db_session, run)
    assert not passed
    assert "autonomous_mode_enabled" in reason


@pytest.mark.asyncio
async def test_gate_blocks_when_kill_switch_active(db_session):
    user, channel = await _make_user_and_channel(db_session)
    rule = await publishing_service.get_or_create_rule(db_session, user.id, channel.id)
    await publishing_service.update_rule(db_session, rule, is_enabled=True)
    await kill_switch.activate(db_session, user.id, "emergency stop for test")

    run = await publishing_service.create_run(
        db_session, user.id, channel.id, None, PublishingMode.AUTHORIZED_AUTONOMOUS,
        {"title": "A video", "description": "desc", "thumbnail_path": "x.jpg"}, "idem-3",
    )
    passed, checks, reason = await publishing_service.run_safety_gate(db_session, run)
    assert not passed
    assert "kill_switch_not_active" in reason


@pytest.mark.asyncio
async def test_gate_passes_for_valid_assist_mode_run(db_session):
    user, channel = await _make_user_and_channel(db_session)
    run = await publishing_service.create_run(
        db_session, user.id, channel.id, None, PublishingMode.ASSIST,
        {"title": "A valid video", "description": "desc", "thumbnail_path": "x.jpg"}, "idem-4",
    )
    passed, checks, reason = await publishing_service.run_safety_gate(db_session, run)
    assert passed, reason


@pytest.mark.asyncio
async def test_create_run_is_idempotent(db_session):
    user, channel = await _make_user_and_channel(db_session)
    metadata = {"title": "Same video", "description": "desc"}
    run1 = await publishing_service.create_run(
        db_session, user.id, channel.id, None, PublishingMode.ASSIST, metadata, "idem-same"
    )
    run2 = await publishing_service.create_run(
        db_session, user.id, channel.id, None, PublishingMode.ASSIST, metadata, "idem-same"
    )
    assert run1.id == run2.id
