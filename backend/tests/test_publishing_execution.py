"""The production audit found execute_run() referenced in this module's own
docstring ("steps 10-13 happen in execute_run") but never implemented --
an approved PublishingRun could reach READY and then nothing would ever
actually upload it. These tests prove the real implementation: a genuine
upload through the same YouTubeProvider interface OAuth/sync already use,
honest CONFIGURATION_REQUIRED when there's no real file to upload (never a
fabricated success), and that the safety gate is re-checked at execution
time, not only at approval time."""
import uuid

import pytest

from app.jobs import kill_switch
from app.modules.channels.service import build_oauth_state
from app.modules.publishing import service as publishing_service
from app.modules.publishing.models import PublishingMode, PublishingState


async def _oauth_connected_channel(client, db_session):
    email = f"pubexec-{uuid.uuid4().hex[:8]}@example.com"
    register = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "supersecurepassword1"}
    )
    user_id = register.json()["user"]["id"]
    state = build_oauth_state(uuid.UUID(user_id))
    callback = await client.get(
        "/api/v1/channels/oauth/callback", params={"code": "mock-code", "state": state}
    )
    channel_id = callback.headers["location"].split("connected=")[1].split("&")[0]

    from app.modules.channels.models import Channel
    from app.modules.users.models import User

    user = await db_session.get(User, uuid.UUID(user_id))
    channel = await db_session.get(Channel, uuid.UUID(channel_id))
    return user, channel


async def _ready_run(db_session, user, channel, video_file_path=None, idem="exec-idem"):
    run = await publishing_service.create_run(
        db_session, user.id, channel.id, None, PublishingMode.ASSIST,
        {"title": "A real video", "description": "desc", "thumbnail_path": "thumb.jpg"},
        idem, video_file_path=video_file_path,
    )
    passed, checks, reason = await publishing_service.run_safety_gate(db_session, run)
    assert passed, reason
    run = await publishing_service.approve_run(db_session, run, user.id)
    assert run.state == PublishingState.READY
    return run


@pytest.mark.asyncio
async def test_execute_run_without_video_file_is_configuration_required(client, db_session):
    user, channel = await _oauth_connected_channel(client, db_session)
    run = await _ready_run(db_session, user, channel, video_file_path=None)

    run, result = await publishing_service.execute_run(db_session, run)

    assert result == "configuration_required"
    assert run.state == PublishingState.FAILED
    assert "CONFIGURATION_REQUIRED" in run.failure_reason
    assert run.published_url is None


@pytest.mark.asyncio
async def test_execute_run_rejects_disallowed_file_extension(client, db_session, tmp_path):
    user, channel = await _oauth_connected_channel(client, db_session)
    bad_file = tmp_path / "video.exe"
    bad_file.write_bytes(b"not a video")
    run = await _ready_run(db_session, user, channel, video_file_path=str(bad_file), idem="exec-badext")

    run, result = await publishing_service.execute_run(db_session, run)

    assert result == "failed"
    assert run.state == PublishingState.FAILED


@pytest.mark.asyncio
async def test_execute_run_uploads_and_publishes_real_file(client, db_session, tmp_path):
    user, channel = await _oauth_connected_channel(client, db_session)
    video_file = tmp_path / "real_video.mp4"
    video_file.write_bytes(b"fake mp4 bytes for testing")
    run = await _ready_run(db_session, user, channel, video_file_path=str(video_file), idem="exec-success")

    run, result = await publishing_service.execute_run(db_session, run)

    assert result == "succeeded"
    assert run.state == PublishingState.PUBLISHED
    assert run.youtube_video_id == "mockuploadvid"
    assert run.published_url == "https://www.youtube.com/watch?v=mockuploadvid"
    assert run.published_at is not None


@pytest.mark.asyncio
async def test_execute_run_refuses_a_run_not_in_ready_state(client, db_session, tmp_path):
    user, channel = await _oauth_connected_channel(client, db_session)
    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"bytes")
    run = await publishing_service.create_run(
        db_session, user.id, channel.id, None, PublishingMode.ASSIST,
        {"title": "t", "description": "d"}, "exec-notready", video_file_path=str(video_file),
    )
    assert run.state == PublishingState.DRAFT  # never approved

    run, result = await publishing_service.execute_run(db_session, run)

    assert result == "blocked"
    assert run.state == PublishingState.DRAFT  # untouched


@pytest.mark.asyncio
async def test_execute_run_rechecks_safety_gate_at_execution_time(client, db_session, tmp_path):
    """Approved while the kill switch was off; activated afterwards --
    execution must catch this, not just approval time."""
    user, channel = await _oauth_connected_channel(client, db_session)
    rule = await publishing_service.get_or_create_rule(db_session, user.id, channel.id)
    await publishing_service.update_rule(db_session, rule, mode=PublishingMode.AUTHORIZED_AUTONOMOUS, is_enabled=True)

    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"bytes")
    run = await publishing_service.create_run(
        db_session, user.id, channel.id, None, PublishingMode.AUTHORIZED_AUTONOMOUS,
        {"title": "t", "description": "d", "thumbnail_path": "thumb.jpg"}, "exec-killswitch",
        video_file_path=str(video_file),
    )
    passed, _, reason = await publishing_service.run_safety_gate(db_session, run)
    assert passed, reason
    run = await publishing_service.approve_run(db_session, run, user.id)

    await kill_switch.activate(db_session, user.id, "emergency stop")

    run, result = await publishing_service.execute_run(db_session, run)

    assert result == "blocked"
    assert run.state == PublishingState.FAILED
    assert "kill_switch_not_active" in run.failure_reason


@pytest.mark.asyncio
async def test_poll_pending_publishing_runs_finalizes_processing_runs(client, db_session):
    """Simulates a run stuck in PROCESSING (uploaded but not yet
    verifiable at execute-time) -- the periodic poll must finalize it."""
    user, channel = await _oauth_connected_channel(client, db_session)
    run = await publishing_service.create_run(
        db_session, user.id, channel.id, None, PublishingMode.ASSIST,
        {"title": "t", "description": "d"}, "exec-poll",
    )
    run.state = PublishingState.PROCESSING
    run.youtube_video_id = "mockuploadvid"
    await db_session.commit()

    transitioned = await publishing_service.poll_pending_publishing_runs(db_session)

    assert transitioned == 1
    await db_session.refresh(run)
    assert run.state == PublishingState.PUBLISHED
    assert run.published_url == "https://www.youtube.com/watch?v=mockuploadvid"
