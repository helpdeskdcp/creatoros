"""The production audit found execute_run() referenced in this module's own
docstring ("steps 10-13 happen in execute_run") but never implemented --
an approved PublishingRun could reach READY and then nothing would ever
actually upload it. These tests prove the real implementation: a genuine
upload through the same YouTubeProvider interface OAuth/sync already use,
honest CONFIGURATION_REQUIRED when there's no real file to upload (never a
fabricated success), that the safety gate is re-checked at execution
time (not only at approval time), and that a run can only ever reference
a video file the run's own owner actually uploaded (never an arbitrary
server path or another user's asset)."""
import io
import uuid
from datetime import UTC, datetime

import pytest

from app.jobs import kill_switch
from app.modules.channels.service import build_oauth_state
from app.modules.media.models import MediaAsset, MediaPurpose
from app.modules.publishing import service as publishing_service
from app.modules.publishing.models import PublishingMode, PublishingState


async def _oauth_connected_channel(client, db_session):
    email = f"pubexec-{uuid.uuid4().hex[:8]}@example.com"
    register = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "supersecurepassword1"}
    )
    token = register.json()["access_token"]
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
    return user, channel, token


async def _upload_real_video(client, token: str) -> str:
    resp = await client.post(
        "/api/v1/media/upload",
        data={"purpose": "VIDEO"},
        files={"file": ("real_video.mp4", io.BytesIO(b"fake mp4 bytes for testing"), "video/mp4")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _ready_run(db_session, user, channel, media_asset_id=None, idem="exec-idem"):
    run = await publishing_service.create_run(
        db_session, user.id, channel.id, None, PublishingMode.ASSIST,
        {"title": "A real video", "description": "desc", "thumbnail_path": "thumb.jpg"},
        idem, media_asset_id=uuid.UUID(media_asset_id) if media_asset_id else None,
    )
    passed, checks, reason = await publishing_service.run_safety_gate(db_session, run)
    assert passed, reason
    run = await publishing_service.approve_run(db_session, run, user.id)
    assert run.state == PublishingState.READY
    return run


@pytest.mark.asyncio
async def test_media_upload_rejects_disallowed_extension(client, db_session):
    _, _, token = await _oauth_connected_channel(client, db_session)
    resp = await client.post(
        "/api/v1/media/upload",
        data={"purpose": "VIDEO"},
        files={"file": ("malware.exe", io.BytesIO(b"not a video"), "application/octet-stream")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_execute_run_without_video_file_is_configuration_required(client, db_session):
    user, channel, _ = await _oauth_connected_channel(client, db_session)
    run = await _ready_run(db_session, user, channel, media_asset_id=None)

    run, result = await publishing_service.execute_run(db_session, run)

    assert result == "configuration_required"
    assert run.state == PublishingState.FAILED
    assert "CONFIGURATION_REQUIRED" in run.failure_reason
    assert run.published_url is None


@pytest.mark.asyncio
async def test_execute_run_rejects_a_media_asset_with_disallowed_extension(client, db_session):
    """Defense-in-depth backstop: even if a MediaAsset row somehow points
    at a non-video key (should be impossible via the real upload
    endpoint, which validates this first), execute_run refuses it too."""
    user, channel, _ = await _oauth_connected_channel(client, db_session)
    bad_asset = MediaAsset(
        owner_user_id=user.id, purpose=MediaPurpose.VIDEO, storage_backend="local",
        storage_key="video/x/y.exe", original_filename="y.exe", content_type="application/octet-stream",
        size_bytes=10, created_at=datetime.now(UTC),
    )
    db_session.add(bad_asset)
    await db_session.commit()
    await db_session.refresh(bad_asset)

    run = await _ready_run(db_session, user, channel, media_asset_id=str(bad_asset.id), idem="exec-badext")
    run, result = await publishing_service.execute_run(db_session, run)

    assert result == "configuration_required"  # file doesn't exist on disk either
    assert run.state == PublishingState.FAILED


@pytest.mark.asyncio
async def test_execute_run_uploads_and_publishes_real_file(client, db_session):
    user, channel, token = await _oauth_connected_channel(client, db_session)
    asset_id = await _upload_real_video(client, token)
    run = await _ready_run(db_session, user, channel, media_asset_id=asset_id, idem="exec-success")

    run, result = await publishing_service.execute_run(db_session, run)

    assert result == "succeeded"
    assert run.state == PublishingState.PUBLISHED
    assert run.youtube_video_id == "mockuploadvid"
    assert run.published_url == "https://www.youtube.com/watch?v=mockuploadvid"
    assert run.published_at is not None


@pytest.mark.asyncio
async def test_execute_run_refuses_another_users_media_asset(client, db_session):
    """A run can never publish a video another user uploaded, even if
    someone gets a foreign asset id into a run's media_asset_id."""
    from app.modules.users.models import User, UserRole

    user, channel, _ = await _oauth_connected_channel(client, db_session)

    other_user = User(email="other-owner@example.com", hashed_password="x", role=UserRole.OWNER)
    db_session.add(other_user)
    await db_session.flush()
    foreign_asset = MediaAsset(
        owner_user_id=other_user.id, purpose=MediaPurpose.VIDEO, storage_backend="local",
        storage_key="video/other/real.mp4", original_filename="real.mp4", content_type="video/mp4",
        size_bytes=100, created_at=datetime.now(UTC),
    )
    db_session.add(foreign_asset)
    await db_session.commit()
    await db_session.refresh(foreign_asset)

    run = await publishing_service.create_run(
        db_session, user.id, channel.id, None, PublishingMode.ASSIST,
        {"title": "t", "description": "d", "thumbnail_path": "thumb.jpg"}, "exec-foreign",
        media_asset_id=foreign_asset.id,
    )
    passed, _, reason = await publishing_service.run_safety_gate(db_session, run)
    assert passed, reason
    run = await publishing_service.approve_run(db_session, run, user.id)

    run, result = await publishing_service.execute_run(db_session, run)

    assert result == "configuration_required"
    assert run.state == PublishingState.FAILED


@pytest.mark.asyncio
async def test_execute_run_refuses_a_run_not_in_ready_state(client, db_session):
    user, channel, token = await _oauth_connected_channel(client, db_session)
    asset_id = await _upload_real_video(client, token)
    run = await publishing_service.create_run(
        db_session, user.id, channel.id, None, PublishingMode.ASSIST,
        {"title": "t", "description": "d"}, "exec-notready", media_asset_id=uuid.UUID(asset_id),
    )
    assert run.state == PublishingState.DRAFT  # never approved

    run, result = await publishing_service.execute_run(db_session, run)

    assert result == "blocked"
    assert run.state == PublishingState.DRAFT  # untouched


@pytest.mark.asyncio
async def test_execute_run_rechecks_safety_gate_at_execution_time(client, db_session):
    """Approved while the kill switch was off; activated afterwards --
    execution must catch this, not just approval time."""
    user, channel, token = await _oauth_connected_channel(client, db_session)
    rule = await publishing_service.get_or_create_rule(db_session, user.id, channel.id)
    await publishing_service.update_rule(db_session, rule, mode=PublishingMode.AUTHORIZED_AUTONOMOUS, is_enabled=True)

    asset_id = await _upload_real_video(client, token)
    run = await publishing_service.create_run(
        db_session, user.id, channel.id, None, PublishingMode.AUTHORIZED_AUTONOMOUS,
        {"title": "t", "description": "d", "thumbnail_path": "thumb.jpg"}, "exec-killswitch",
        media_asset_id=uuid.UUID(asset_id),
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
    user, channel, _ = await _oauth_connected_channel(client, db_session)
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
