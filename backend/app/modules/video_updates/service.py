"""Verified Update Engine service: propose -> approve -> execute -> verify.

Every state transition here follows the same rule: a local database write is
never treated as proof that YouTube changed. `approve_and_execute()` always
re-fetches the video from YouTube after the write and only marks
SUCCEEDED_VERIFIED if the live value actually matches what was proposed;
otherwise FAILED_NOT_VERIFIED, with the real error captured.
"""
import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.timeutils import ensure_aware
from app.modules.audit import service as audit_service
from app.modules.channels.models import Channel
from app.modules.channels.providers import get_youtube_provider
from app.modules.channels.providers.base import YouTubeProviderError
from app.modules.channels.service import _get_valid_access_token
from app.modules.experiments.learning import _upsert_signal
from app.modules.notifications.models import NotificationChannel, NotificationEvent
from app.modules.notifications.service import notify
from app.modules.video_updates.models import (
    VideoUpdateField,
    VideoUpdateImpact,
    VideoUpdateProposal,
    VideoUpdateStatus,
)
from app.modules.videos.models import Video, VideoMetricSnapshot

_MAX_TITLE_LEN = 100
_MAX_DESCRIPTION_LEN = 5000
_MAX_TAGS_TOTAL_LEN = 500


async def get_owned_video(db: AsyncSession, video_id: uuid.UUID, owner_user_id: uuid.UUID) -> Video:
    """Video has no owner column of its own -- ownership flows through its
    parent Channel (same JOIN pattern as experiments.get_owned_variant)."""
    video = await db.scalar(
        select(Video)
        .join(Channel, Channel.id == Video.channel_id)
        .where(Video.id == video_id, Channel.owner_user_id == owner_user_id)
    )
    if not video:
        raise NotFoundError("Video not found")
    return video


async def get_owned_proposal(
    db: AsyncSession, proposal_id: uuid.UUID, owner_user_id: uuid.UUID
) -> VideoUpdateProposal:
    proposal = await db.scalar(
        select(VideoUpdateProposal).where(
            VideoUpdateProposal.id == proposal_id,
            VideoUpdateProposal.owner_user_id == owner_user_id,
        )
    )
    if not proposal:
        raise NotFoundError("Video update proposal not found")
    return proposal


def _encode(field: VideoUpdateField, value) -> str:
    return json.dumps(value) if field is VideoUpdateField.TAGS else str(value)


def _decode(field: VideoUpdateField, raw: str | None):
    if raw is None:
        return None
    return json.loads(raw) if field is VideoUpdateField.TAGS else raw


def _validate(field: VideoUpdateField, value) -> None:
    if field is VideoUpdateField.TITLE:
        if not value or not value.strip():
            raise ValidationError("Title cannot be empty")
        if len(value) > _MAX_TITLE_LEN:
            raise ValidationError(f"Title exceeds YouTube's {_MAX_TITLE_LEN}-character limit")
    elif field is VideoUpdateField.DESCRIPTION:
        if len(value or "") > _MAX_DESCRIPTION_LEN:
            raise ValidationError(f"Description exceeds YouTube's {_MAX_DESCRIPTION_LEN}-character limit")
    elif field is VideoUpdateField.TAGS:
        if not isinstance(value, list) or not all(isinstance(t, str) for t in value):
            raise ValidationError("Tags must be a list of strings")
        if sum(len(t) for t in value) > _MAX_TAGS_TOTAL_LEN:
            raise ValidationError(f"Combined tag length exceeds YouTube's {_MAX_TAGS_TOTAL_LEN}-character limit")


async def propose_update(
    db: AsyncSession,
    owner_user_id: uuid.UUID,
    video_id: uuid.UUID,
    field: VideoUpdateField,
    proposed_value,
    reason: str,
    evidence: str | None = None,
) -> VideoUpdateProposal:
    video = await get_owned_video(db, video_id, owner_user_id)
    _validate(field, proposed_value)

    current_value = {
        VideoUpdateField.TITLE: video.title,
        VideoUpdateField.DESCRIPTION: video.description,
        VideoUpdateField.TAGS: (video.tags.split(",") if video.tags else []),
    }[field]

    proposal = VideoUpdateProposal(
        video_id=video.id,
        owner_user_id=owner_user_id,
        field=field,
        previous_value=_encode(field, current_value),
        proposed_value=_encode(field, proposed_value),
        reason=reason,
        evidence=evidence,
        status=VideoUpdateStatus.PENDING_APPROVAL,
    )
    db.add(proposal)
    await db.commit()
    await db.refresh(proposal)
    await audit_service.record(
        db, action_type="video_update_proposed", result="success", user_id=owner_user_id,
        content_id=str(video.youtube_video_id),
        before_state={"field": field.value, "value": current_value},
        after_state={"field": field.value, "proposed_value": proposed_value},
    )
    return proposal


async def reject_proposal(db: AsyncSession, proposal_id: uuid.UUID, owner_user_id: uuid.UUID) -> VideoUpdateProposal:
    proposal = await get_owned_proposal(db, proposal_id, owner_user_id)
    if proposal.status != VideoUpdateStatus.PENDING_APPROVAL:
        raise ConflictError(f"Proposal is {proposal.status.value}, not PENDING_APPROVAL")
    proposal.status = VideoUpdateStatus.REJECTED
    await db.commit()
    await audit_service.record(
        db, action_type="video_update_rejected", result="success", user_id=owner_user_id,
    )
    return proposal


async def _notify_update_failed(db: AsyncSession, proposal: VideoUpdateProposal, video: Video) -> None:
    # Reuses PUBLISHING_RESULT rather than adding a new enum value (which
    # would need an ALTER TYPE migration) -- semantically this is exactly
    # that category: the result of a YouTube-facing write operation.
    await notify(
        db, proposal.owner_user_id, NotificationEvent.PUBLISHING_RESULT, NotificationChannel.IN_APP,
        f"YouTube update failed for \"{video.title}\"",
        f"Proposed {proposal.field.value.lower()} change was not applied/verified: {proposal.error_message}",
    )


async def approve_and_execute(
    db: AsyncSession, proposal_id: uuid.UUID, owner_user_id: uuid.UUID
) -> VideoUpdateProposal:
    """The only path that ever writes to YouTube for an existing video.
    Fetches the CURRENT live snippet first (never trusts local cache as the
    merge base), applies the one proposed field, writes it, then
    independently re-fetches to verify -- never marks success on the write
    call's own echoed response alone."""
    proposal = await get_owned_proposal(db, proposal_id, owner_user_id)
    if proposal.status != VideoUpdateStatus.PENDING_APPROVAL:
        raise ConflictError(f"Proposal is {proposal.status.value}, not PENDING_APPROVAL")

    video = await db.get(Video, proposal.video_id)
    channel = await db.get(Channel, video.channel_id)

    proposal.status = VideoUpdateStatus.EXECUTING
    proposal.approved_by_user_id = owner_user_id
    proposal.approved_at = datetime.now(UTC)
    await db.commit()

    provider = get_youtube_provider()
    access_token = await _get_valid_access_token(db, channel)
    if not access_token:
        proposal.status = VideoUpdateStatus.FAILED_NOT_VERIFIED
        proposal.error_message = "Channel has no valid OAuth grant to write to YouTube"
        proposal.executed_at = datetime.now(UTC)
        await db.commit()
        await audit_service.record(
            db, action_type="video_update_executed", result="failure", user_id=owner_user_id,
            failure_reason=proposal.error_message,
        )
        await _notify_update_failed(db, proposal, video)
        return proposal

    proposed_value = _decode(proposal.field, proposal.proposed_value)
    kwargs = {
        VideoUpdateField.TITLE: {"title": proposed_value},
        VideoUpdateField.DESCRIPTION: {"description": proposed_value},
        VideoUpdateField.TAGS: {"tags": proposed_value},
    }[proposal.field]

    try:
        # Live pre-write snapshot -- the authoritative previous_value (may
        # differ from what CreatorOS last synced if it changed on YouTube
        # since), and what update_video_metadata merges the change onto.
        pre_state = (await provider.get_video_details([video.youtube_video_id]))[0]
        proposal.verified_previous_value = _encode(
            proposal.field,
            {
                VideoUpdateField.TITLE: pre_state.title,
                VideoUpdateField.DESCRIPTION: pre_state.description,
                VideoUpdateField.TAGS: pre_state.tags,
            }[proposal.field],
        )

        await provider.update_video_metadata(access_token, video.youtube_video_id, **kwargs)

        # Independent read-back -- verification never trusts the write
        # call's own response alone.
        post_state = (await provider.get_video_details([video.youtube_video_id]))[0]
        actual_value = {
            VideoUpdateField.TITLE: post_state.title,
            VideoUpdateField.DESCRIPTION: post_state.description,
            VideoUpdateField.TAGS: post_state.tags,
        }[proposal.field]
        verified = actual_value == proposed_value
    except YouTubeProviderError as exc:
        proposal.status = VideoUpdateStatus.FAILED_NOT_VERIFIED
        proposal.error_message = str(exc)
        proposal.executed_at = datetime.now(UTC)
        await db.commit()
        await audit_service.record(
            db, action_type="video_update_executed", result="failure", user_id=owner_user_id,
            content_id=str(video.youtube_video_id), failure_reason=str(exc),
        )
        await _notify_update_failed(db, proposal, video)
        return proposal

    proposal.executed_at = datetime.now(UTC)
    if verified:
        proposal.status = VideoUpdateStatus.SUCCEEDED_VERIFIED
        proposal.verified_at = datetime.now(UTC)
        # Keep the local cache in sync with the now-confirmed live value.
        if proposal.field is VideoUpdateField.TITLE:
            video.title = actual_value
        elif proposal.field is VideoUpdateField.DESCRIPTION:
            video.description = actual_value
        elif proposal.field is VideoUpdateField.TAGS:
            video.tags = ",".join(actual_value)
    else:
        proposal.status = VideoUpdateStatus.FAILED_NOT_VERIFIED
        proposal.error_message = (
            f"YouTube read-back did not match the proposed value after the update call "
            f"(expected {proposed_value!r}, YouTube reports {actual_value!r})"
        )
    await db.commit()
    await audit_service.record(
        db, action_type="video_update_executed", result="success" if verified else "failure",
        user_id=owner_user_id, content_id=str(video.youtube_video_id),
        before_state={"field": proposal.field.value, "value": _decode(proposal.field, proposal.verified_previous_value)},
        after_state={"field": proposal.field.value, "value": actual_value if verified else None},
        failure_reason=None if verified else proposal.error_message,
    )
    if not verified:
        await _notify_update_failed(db, proposal, video)
    return proposal


async def create_rollback(
    db: AsyncSession, proposal_id: uuid.UUID, owner_user_id: uuid.UUID
) -> VideoUpdateProposal:
    """Rollback is itself a new PENDING_APPROVAL proposal reverting to the
    live pre-write value captured at the original execution -- reverting a
    live write is still a live write and goes through the same approval
    gate, never auto-executed."""
    original = await get_owned_proposal(db, proposal_id, owner_user_id)
    if original.status != VideoUpdateStatus.SUCCEEDED_VERIFIED:
        raise ConflictError("Can only roll back a SUCCEEDED_VERIFIED proposal")
    if original.verified_previous_value is None:
        raise ConflictError("No verified previous value recorded for this proposal to roll back to")

    rollback = VideoUpdateProposal(
        video_id=original.video_id,
        owner_user_id=owner_user_id,
        field=original.field,
        previous_value=original.proposed_value,
        proposed_value=original.verified_previous_value,
        reason=f"Rollback of proposal {original.id}",
        evidence=None,
        status=VideoUpdateStatus.PENDING_APPROVAL,
        rollback_of_id=original.id,
    )
    db.add(rollback)
    await db.commit()
    await db.refresh(rollback)
    await audit_service.record(
        db, action_type="video_update_rollback_proposed", result="success", user_id=owner_user_id,
    )
    return rollback


async def list_proposals(
    db: AsyncSession, owner_user_id: uuid.UUID, video_id: uuid.UUID | None = None
) -> list[VideoUpdateProposal]:
    stmt = select(VideoUpdateProposal).where(VideoUpdateProposal.owner_user_id == owner_user_id)
    if video_id is not None:
        stmt = stmt.where(VideoUpdateProposal.video_id == video_id)
    stmt = stmt.order_by(VideoUpdateProposal.created_at.desc())
    return list(await db.scalars(stmt))


_IMPACT_THRESHOLD = 0.15  # +/-15% relative velocity change to call WIN/LOSS
_TOLERANCE_FRACTION = 0.3


async def _closest_snapshot_value(
    db: AsyncSession, video_id: uuid.UUID, target: datetime, tolerance: timedelta
) -> int | None:
    snapshots = list(
        await db.scalars(
            select(VideoMetricSnapshot).where(
                VideoMetricSnapshot.video_id == video_id,
                VideoMetricSnapshot.captured_at >= target - tolerance,
                VideoMetricSnapshot.captured_at <= target + tolerance,
            )
        )
    )
    if not snapshots:
        return None
    closest = min(snapshots, key=lambda s: abs((ensure_aware(s.captured_at) - target).total_seconds()))
    return closest.view_count


async def measure_update_impact(
    db: AsyncSession, proposal_id: uuid.UUID, owner_user_id: uuid.UUID
) -> VideoUpdateProposal:
    """Compares view VELOCITY (views/day) in the window before the change
    to the window after it -- never the raw cumulative view count, which
    only ever increases and would call every change a "win". This is a
    correlational before/after comparison on one channel's own video, not
    a controlled experiment -- it does not and cannot prove the metadata
    change CAUSED the difference; it only measures whether one occurred."""
    proposal = await get_owned_proposal(db, proposal_id, owner_user_id)
    if proposal.status != VideoUpdateStatus.SUCCEEDED_VERIFIED:
        raise ConflictError("Can only measure impact for a SUCCEEDED_VERIFIED proposal")
    if proposal.impact_measured_at is not None:
        raise ConflictError("Impact has already been measured for this proposal")

    executed_at = ensure_aware(proposal.executed_at)
    window = timedelta(days=proposal.observation_window_days)
    now = datetime.now(UTC)
    if now < executed_at + window:
        raise ConflictError(
            f"Observation window ({proposal.observation_window_days} days) has not elapsed yet"
        )

    tolerance = timedelta(days=max(1, proposal.observation_window_days * _TOLERANCE_FRACTION))
    before = await _closest_snapshot_value(db, proposal.video_id, executed_at - window, tolerance)
    at_change = await _closest_snapshot_value(db, proposal.video_id, executed_at, tolerance)
    after = await _closest_snapshot_value(db, proposal.video_id, executed_at + window, tolerance)

    if before is None or at_change is None or after is None:
        proposal.impact_outcome = VideoUpdateImpact.INCONCLUSIVE
        proposal.impact_measured_at = now
        await db.commit()
        return proposal

    proposal.baseline_view_velocity = max(0, at_change - before) / proposal.observation_window_days
    proposal.post_view_velocity = max(0, after - at_change) / proposal.observation_window_days

    if proposal.baseline_view_velocity == 0:
        outcome = (
            VideoUpdateImpact.WIN if proposal.post_view_velocity > 0 else VideoUpdateImpact.INCONCLUSIVE
        )
    else:
        delta_ratio = (
            (proposal.post_view_velocity - proposal.baseline_view_velocity) / proposal.baseline_view_velocity
        )
        if delta_ratio >= _IMPACT_THRESHOLD:
            outcome = VideoUpdateImpact.WIN
        elif delta_ratio <= -_IMPACT_THRESHOLD:
            outcome = VideoUpdateImpact.LOSS
        else:
            outcome = VideoUpdateImpact.NEUTRAL

    proposal.impact_outcome = outcome
    proposal.impact_measured_at = now
    await db.commit()

    # Only decisive outcomes feed the learning loop -- NEUTRAL/INCONCLUSIVE
    # are real, honest results but not a signal either way.
    if outcome in (VideoUpdateImpact.WIN, VideoUpdateImpact.LOSS):
        await _upsert_signal(
            db, owner_user_id, "video_metadata_update", proposal.field.value,
            won=outcome is VideoUpdateImpact.WIN,
        )
        await db.commit()

    await audit_service.record(
        db, action_type="video_update_impact_measured", result="success", user_id=owner_user_id,
        content_id=str(proposal.video_id),
        after_state={
            "outcome": outcome.value,
            "baseline_velocity": proposal.baseline_view_velocity,
            "post_velocity": proposal.post_view_velocity,
        },
    )
    return proposal


async def list_measurable_proposals(db: AsyncSession) -> list[VideoUpdateProposal]:
    """SUCCEEDED_VERIFIED proposals whose observation window has elapsed
    and haven't been measured yet -- used by the periodic measurement job."""
    now = datetime.now(UTC)
    candidates = list(
        await db.scalars(
            select(VideoUpdateProposal).where(
                VideoUpdateProposal.status == VideoUpdateStatus.SUCCEEDED_VERIFIED,
                VideoUpdateProposal.impact_measured_at.is_(None),
                VideoUpdateProposal.executed_at.is_not(None),
            )
        )
    )
    return [
        p for p in candidates
        if now >= ensure_aware(p.executed_at) + timedelta(days=p.observation_window_days)
    ]
