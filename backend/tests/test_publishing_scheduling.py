"""Real scheduled publishing: SCHEDULED/RETRY_PENDING/CANCELLED existed as
unused enum values before this -- approving a run always published
immediately, with no durable "publish later" concept and no way to
cancel or reschedule. These tests exercise the full state machine using
deterministic time control (setting scheduled_at relative to real "now",
never a real sleep or a mocked clock object) and the mock YouTube
provider throughout -- no real production publishing occurs in any test
here, per the explicit instruction not to."""
import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import ConflictError
from app.modules.channels.service import build_oauth_state
from app.modules.publishing import service as publishing_service
from app.modules.publishing.models import PublishingMode, PublishingState


async def _oauth_connected_channel(client, db_session):
    email = f"sched-{uuid.uuid4().hex[:8]}@example.com"
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


async def _upload_real_video(client, token: str) -> uuid.UUID:
    resp = await client.post(
        "/api/v1/media/upload",
        data={"purpose": "VIDEO"},
        files={"file": ("video.mp4", io.BytesIO(b"fake mp4 bytes"), "video/mp4")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


@pytest.mark.asyncio
async def test_scheduled_at_requires_timezone(client, db_session):
    _, _, token = await _oauth_connected_channel(client, db_session)
    resp = await client.post(
        "/api/v1/publishing/runs",
        json={
            "channel_id": str(uuid.uuid4()), "mode": "ASSIST", "idempotency_key": "naive-tz",
            "title": "t", "description": "d", "scheduled_at": "2027-01-01T00:00:00",  # no offset
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_approve_run_with_future_schedule_does_not_publish_immediately(client, db_session):
    user, channel, token = await _oauth_connected_channel(client, db_session)
    asset_id = await _upload_real_video(client, token)
    future = datetime.now(UTC) + timedelta(hours=2)

    run = await publishing_service.create_run(
        db_session, user.id, channel.id, None, PublishingMode.ASSIST,
        {"title": "t", "description": "d", "thumbnail_path": "thumb.jpg"}, "sched-future",
        media_asset_id=asset_id, scheduled_at=future,
    )
    passed, _, reason = await publishing_service.run_safety_gate(db_session, run)
    assert passed, reason

    run = await publishing_service.approve_run(db_session, run, user.id)

    assert run.state == PublishingState.SCHEDULED
    assert run.requires_approval is False  # approval itself still happened


@pytest.mark.asyncio
async def test_approve_run_with_past_schedule_is_immediately_ready(client, db_session):
    """A schedule already in the past behaves exactly like no schedule --
    immediately eligible, matching pre-scheduling behavior."""
    user, channel, token = await _oauth_connected_channel(client, db_session)
    asset_id = await _upload_real_video(client, token)
    past = datetime.now(UTC) - timedelta(minutes=5)

    run = await publishing_service.create_run(
        db_session, user.id, channel.id, None, PublishingMode.ASSIST,
        {"title": "t", "description": "d", "thumbnail_path": "thumb.jpg"}, "sched-past",
        media_asset_id=asset_id, scheduled_at=past,
    )
    await publishing_service.run_safety_gate(db_session, run)
    run = await publishing_service.approve_run(db_session, run, user.id)

    assert run.state == PublishingState.READY


@pytest.mark.asyncio
async def test_claim_due_scheduled_run_ids_claims_only_due_runs(client, db_session):
    user, channel, token = await _oauth_connected_channel(client, db_session)
    asset_id = await _upload_real_video(client, token)

    due_run = await publishing_service.create_run(
        db_session, user.id, channel.id, None, PublishingMode.ASSIST,
        {"title": "t", "description": "d", "thumbnail_path": "thumb.jpg"}, "claim-due",
        media_asset_id=asset_id, scheduled_at=datetime.now(UTC) + timedelta(seconds=1),
    )
    await publishing_service.run_safety_gate(db_session, due_run)
    due_run = await publishing_service.approve_run(db_session, due_run, user.id)
    assert due_run.state == PublishingState.SCHEDULED

    not_due_run = await publishing_service.create_run(
        db_session, user.id, channel.id, None, PublishingMode.ASSIST,
        {"title": "t2", "description": "d", "thumbnail_path": "thumb.jpg"}, "claim-not-due",
        media_asset_id=asset_id, scheduled_at=datetime.now(UTC) + timedelta(hours=5),
    )
    await publishing_service.run_safety_gate(db_session, not_due_run)
    not_due_run = await publishing_service.approve_run(db_session, not_due_run, user.id)
    assert not_due_run.state == PublishingState.SCHEDULED

    # Simulate time passing (deterministic: move the due run's schedule
    # into the past) rather than a real sleep.
    due_run.scheduled_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    claimed = await publishing_service.claim_due_scheduled_run_ids(db_session)

    assert claimed == [due_run.id]
    await db_session.refresh(due_run)
    await db_session.refresh(not_due_run)
    assert due_run.state == PublishingState.READY
    assert not_due_run.state == PublishingState.SCHEDULED  # untouched


@pytest.mark.asyncio
async def test_claim_due_scheduled_run_ids_never_double_claims(client, db_session):
    """The exact race the atomic UPDATE...WHERE guards against: two
    overlapping poll ticks must never both claim (and therefore never
    both dispatch execution for) the same run."""
    user, channel, token = await _oauth_connected_channel(client, db_session)
    asset_id = await _upload_real_video(client, token)
    run = await publishing_service.create_run(
        db_session, user.id, channel.id, None, PublishingMode.ASSIST,
        {"title": "t", "description": "d", "thumbnail_path": "thumb.jpg"}, "claim-once",
        media_asset_id=asset_id, scheduled_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await publishing_service.run_safety_gate(db_session, run)
    run = await publishing_service.approve_run(db_session, run, user.id)
    assert run.state == PublishingState.SCHEDULED

    # Simulate the scheduled hour passing (deterministic, no real sleep).
    run.scheduled_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    first_claim = await publishing_service.claim_due_scheduled_run_ids(db_session)
    second_claim = await publishing_service.claim_due_scheduled_run_ids(db_session)

    assert first_claim == [run.id]
    assert second_claim == []  # already READY -- no longer SCHEDULED, can't be claimed again


@pytest.mark.asyncio
async def test_full_scheduled_publish_journey_end_to_end(client, db_session):
    """The complete realistic flow a creator + the poller would produce:
    schedule for the future, approve, wait (simulated), get claimed,
    execute, and actually publish -- all through the mock provider."""
    user, channel, token = await _oauth_connected_channel(client, db_session)
    asset_id = await _upload_real_video(client, token)

    run = await publishing_service.create_run(
        db_session, user.id, channel.id, None, PublishingMode.ASSIST,
        {"title": "Scheduled video", "description": "d", "thumbnail_path": "thumb.jpg"}, "e2e-scheduled",
        media_asset_id=asset_id, scheduled_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await publishing_service.run_safety_gate(db_session, run)
    run = await publishing_service.approve_run(db_session, run, user.id)
    assert run.state == PublishingState.SCHEDULED

    # Simulate the scheduled hour passing.
    run.scheduled_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    claimed = await publishing_service.claim_due_scheduled_run_ids(db_session)
    assert claimed == [run.id]
    await db_session.refresh(run)
    assert run.state == PublishingState.READY

    run, result = await publishing_service.execute_run(db_session, run)

    assert result == "succeeded"
    assert run.state == PublishingState.PUBLISHED
    assert run.published_url == "https://www.youtube.com/watch?v=mockuploadvid"


@pytest.mark.asyncio
async def test_cancel_run_from_scheduled_state(client, db_session):
    user, channel, token = await _oauth_connected_channel(client, db_session)
    asset_id = await _upload_real_video(client, token)
    run = await publishing_service.create_run(
        db_session, user.id, channel.id, None, PublishingMode.ASSIST,
        {"title": "t", "description": "d", "thumbnail_path": "thumb.jpg"}, "cancel-scheduled",
        media_asset_id=asset_id, scheduled_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await publishing_service.run_safety_gate(db_session, run)
    run = await publishing_service.approve_run(db_session, run, user.id)
    assert run.state == PublishingState.SCHEDULED

    run = await publishing_service.cancel_run(db_session, run, user.id)

    assert run.state == PublishingState.CANCELLED
    assert run.cancelled_at is not None
    assert run.cancelled_by_user_id == user.id

    # A cancelled run must never be claimable by the poller.
    claimed = await publishing_service.claim_due_scheduled_run_ids(db_session)
    assert run.id not in claimed


@pytest.mark.asyncio
async def test_cancel_run_refuses_once_upload_has_started(client, db_session):
    user, channel, token = await _oauth_connected_channel(client, db_session)
    asset_id = await _upload_real_video(client, token)
    run = await publishing_service.create_run(
        db_session, user.id, channel.id, None, PublishingMode.ASSIST,
        {"title": "t", "description": "d"}, "cancel-uploading", media_asset_id=asset_id,
    )
    run.state = PublishingState.UPLOADING
    await db_session.commit()

    with pytest.raises(ConflictError):
        await publishing_service.cancel_run(db_session, run, user.id)


@pytest.mark.asyncio
async def test_reschedule_run_moves_ready_run_back_to_scheduled(client, db_session):
    user, channel, token = await _oauth_connected_channel(client, db_session)
    asset_id = await _upload_real_video(client, token)
    run = await publishing_service.create_run(
        db_session, user.id, channel.id, None, PublishingMode.ASSIST,
        {"title": "t", "description": "d", "thumbnail_path": "thumb.jpg"}, "reschedule-1",
        media_asset_id=asset_id,
    )
    await publishing_service.run_safety_gate(db_session, run)
    run = await publishing_service.approve_run(db_session, run, user.id)
    assert run.state == PublishingState.READY  # no schedule -> immediate

    future = datetime.now(UTC) + timedelta(days=1)
    run = await publishing_service.reschedule_run(db_session, run, user.id, future)

    assert run.state == PublishingState.SCHEDULED
    # SQLite (test-only) doesn't round-trip tzinfo on DateTime columns the
    # way Postgres does -- compare the actual instants, not object equality.
    from app.core.timeutils import ensure_aware

    assert ensure_aware(run.scheduled_at) == future


@pytest.mark.asyncio
async def test_reschedule_run_refuses_once_upload_has_started(client, db_session):
    user, channel, token = await _oauth_connected_channel(client, db_session)
    asset_id = await _upload_real_video(client, token)
    run = await publishing_service.create_run(
        db_session, user.id, channel.id, None, PublishingMode.ASSIST,
        {"title": "t", "description": "d"}, "reschedule-uploading", media_asset_id=asset_id,
    )
    run.state = PublishingState.PROCESSING
    await db_session.commit()

    with pytest.raises(ConflictError):
        await publishing_service.reschedule_run(db_session, run, user.id, datetime.now(UTC) + timedelta(hours=1))


@pytest.mark.asyncio
async def test_cancel_and_reschedule_endpoints_refuse_another_users_run(client, db_session):
    """Adversarial: get_owned_or_404 must gate these new endpoints exactly
    like every other owned-resource endpoint in the app."""
    user, channel, token = await _oauth_connected_channel(client, db_session)
    asset_id = await _upload_real_video(client, token)
    run = await publishing_service.create_run(
        db_session, user.id, channel.id, None, PublishingMode.ASSIST,
        {"title": "t", "description": "d", "thumbnail_path": "thumb.jpg"}, "adversarial-run",
        media_asset_id=asset_id, scheduled_at=datetime.now(UTC) + timedelta(hours=1),
    )
    await publishing_service.run_safety_gate(db_session, run)
    await publishing_service.approve_run(db_session, run, user.id)

    from app.modules.users.models import User, UserRole

    attacker = User(email="attacker@example.com", hashed_password="x", role=UserRole.OWNER)
    db_session.add(attacker)
    await db_session.commit()
    from app.core.security import create_jwt

    attacker_token, _ = create_jwt(subject=str(attacker.id), token_type="access")
    headers = {"Authorization": f"Bearer {attacker_token}"}

    cancel_resp = await client.post(f"/api/v1/publishing/runs/{run.id}/cancel", headers=headers)
    reschedule_resp = await client.patch(
        f"/api/v1/publishing/runs/{run.id}/reschedule",
        json={"scheduled_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat()},
        headers=headers,
    )
    execute_resp = await client.post(f"/api/v1/publishing/runs/{run.id}/execute", headers=headers)

    assert cancel_resp.status_code == 404
    assert reschedule_resp.status_code == 404
    assert execute_resp.status_code == 404

    await db_session.refresh(run)
    assert run.state == PublishingState.SCHEDULED  # untouched by the attacker
