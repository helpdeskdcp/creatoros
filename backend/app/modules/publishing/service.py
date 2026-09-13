"""Publishing safety gate + state machine. Extends Channel/YouTubeProvider —
this module owns authorization/rules/idempotency; app.modules.channels.providers
still owns the actual YouTube API calls.

Every automated publish passes through run_safety_gate() before any upload
call is made. A failed gate blocks the action (BLOCK_ACTION) and is always
recorded, win or lose, in publishing_attempts + audit_logs.
"""
import json
import os
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.core.logging import get_logger
from app.core.timeutils import ensure_aware
from app.jobs import kill_switch
from app.modules.audit import service as audit_service
from app.modules.channels.models import Channel
from app.modules.channels.providers import get_youtube_provider
from app.modules.channels.providers.base import UploadMetadata, YouTubeProviderError
from app.modules.channels.service import _get_valid_access_token
from app.modules.publishing.models import (
    PublishingAttempt,
    PublishingMode,
    PublishingRule,
    PublishingRun,
    PublishingState,
)

logger = get_logger("publishing.service")

_ALLOWED_VIDEO_EXTENSIONS = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024 * 1024  # 20GB, YouTube's own ceiling


async def get_or_create_rule(db: AsyncSession, owner_user_id: uuid.UUID, channel_id: uuid.UUID) -> PublishingRule:
    rule = await db.scalar(
        select(PublishingRule).where(
            PublishingRule.owner_user_id == owner_user_id, PublishingRule.channel_id == channel_id
        )
    )
    if not rule:
        rule = PublishingRule(owner_user_id=owner_user_id, channel_id=channel_id, mode=PublishingMode.ASSIST)
        db.add(rule)
        await db.commit()
        await db.refresh(rule)
    return rule


async def update_rule(db: AsyncSession, rule: PublishingRule, **fields) -> PublishingRule:
    for key, value in fields.items():
        if value is not None and hasattr(rule, key):
            setattr(rule, key, value)
    await db.commit()
    await db.refresh(rule)
    return rule


async def create_run(
    db: AsyncSession,
    owner_user_id: uuid.UUID,
    channel_id: uuid.UUID,
    content_item_id: uuid.UUID | None,
    mode: PublishingMode,
    metadata: dict,
    idempotency_key: str,
    media_asset_id: uuid.UUID | None = None,
    scheduled_at: datetime | None = None,
) -> PublishingRun:
    existing = await db.scalar(
        select(PublishingRun).where(PublishingRun.idempotency_key == idempotency_key)
    )
    if existing:
        return existing  # idempotent: never create a duplicate upload for a retried request

    run = PublishingRun(
        owner_user_id=owner_user_id,
        channel_id=channel_id,
        content_item_id=content_item_id,
        idempotency_key=idempotency_key,
        mode=mode,
        state=PublishingState.DRAFT,
        metadata_json=json.dumps(metadata),
        video_media_asset_id=media_asset_id,
        scheduled_at=scheduled_at,
        requires_approval=(mode != PublishingMode.AUTHORIZED_AUTONOMOUS),
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def run_safety_gate(db: AsyncSession, run: PublishingRun) -> tuple[bool, list[dict], str | None]:
    """The 13-step safety gate (steps 10-13 happen in execute_run). Returns
    (passed, checks, block_reason). Always returns a full check list even on
    the first failure so the audit trail shows everything evaluated."""
    checks: list[dict] = []

    def check(name: str, passed: bool, detail: str = "") -> bool:
        checks.append({"check": name, "passed": passed, "detail": detail})
        return passed

    channel = await db.get(Channel, run.channel_id)
    ok = check("channel_ownership", bool(channel and channel.owner_user_id == run.owner_user_id))
    ok = check("oauth_token_present", bool(channel and channel.oauth_access_token_encrypted)) and ok

    rule = await get_or_create_rule(db, run.owner_user_id, run.channel_id)
    ok = check("publishing_mode_matches_rule", rule.mode == run.mode) and ok

    if run.mode == PublishingMode.AUTHORIZED_AUTONOMOUS:
        ok = check("autonomous_mode_enabled", rule.is_enabled) and ok
        ok = check(
            "rule_not_expired",
            rule.expires_at is None or ensure_aware(rule.expires_at) > datetime.now(UTC),
        ) and ok
        kill_active = await kill_switch.is_active(db, run.owner_user_id)
        ok = check("kill_switch_not_active", not kill_active) and ok

        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        runs_today = await db.scalar(
            select(func.count()).select_from(PublishingRun).where(
                PublishingRun.channel_id == run.channel_id,
                PublishingRun.state == PublishingState.PUBLISHED,
                PublishingRun.created_at >= today_start,
            )
        )
        ok = check(
            "within_daily_limit", (runs_today or 0) < rule.max_videos_per_day,
            f"{runs_today}/{rule.max_videos_per_day} published today",
        ) and ok

    metadata = json.loads(run.metadata_json) if run.metadata_json else {}
    ok = check("metadata_has_title", bool(metadata.get("title"))) and ok
    ok = check("metadata_has_description", bool(metadata.get("description"))) and ok
    ok = check(
        "title_length_valid", len(metadata.get("title", "")) <= 100, "YouTube title limit is 100 chars"
    ) and ok
    if rule.require_thumbnail:
        ok = check("thumbnail_provided", bool(metadata.get("thumbnail_path"))) and ok

    content_score = metadata.get("content_score", 0)
    subscriber_score = metadata.get("subscriber_score", 0)
    ok = check(
        "meets_minimum_content_score", content_score >= rule.minimum_content_score,
        f"{content_score} >= {rule.minimum_content_score}",
    ) and ok
    ok = check(
        "meets_minimum_subscriber_score", subscriber_score >= rule.minimum_subscriber_score,
        f"{subscriber_score} >= {rule.minimum_subscriber_score}",
    ) and ok

    block_reason = None if ok else "; ".join(c["check"] for c in checks if not c["passed"])
    return ok, checks, block_reason


async def record_attempt(
    db: AsyncSession, run: PublishingRun, gate_passed: bool, checks: list[dict], result: str, error: str | None
) -> PublishingAttempt:
    attempt_number = (
        (await db.scalar(
            select(func.count()).select_from(PublishingAttempt).where(
                PublishingAttempt.publishing_run_id == run.id
            )
        ))
        or 0
    ) + 1
    attempt = PublishingAttempt(
        publishing_run_id=run.id,
        attempt_number=attempt_number,
        gate_passed=gate_passed,
        gate_checks_json=json.dumps(checks),
        result=result,
        error=error,
    )
    db.add(attempt)
    await db.commit()
    await db.refresh(attempt)

    await audit_service.record(
        db,
        action_type="publishing_attempt",
        result=result,
        user_id=run.owner_user_id,
        channel_id=run.channel_id,
        provider="youtube",
        request_id=None,
        authorization_state="passed" if gate_passed else "blocked",
        rule_set={"checks": checks},
        failure_reason=error,
    )
    return attempt


async def approve_run(db: AsyncSession, run: PublishingRun, approver_user_id: uuid.UUID) -> PublishingRun:
    run.requires_approval = False
    run.approved_by_user_id = approver_user_id
    run.approved_at = datetime.now(UTC)
    # A future scheduled_at must NOT publish immediately -- it sits in
    # SCHEDULED until poll_and_dispatch_due_scheduled_runs atomically
    # claims it once due. A scheduled_at already in the past (or none at
    # all) is immediately eligible, matching the pre-scheduling behavior.
    if run.scheduled_at and ensure_aware(run.scheduled_at) > datetime.now(UTC):
        run.state = PublishingState.SCHEDULED
    else:
        run.state = PublishingState.READY
    await db.commit()
    await db.refresh(run)
    await audit_service.record(
        db, action_type="publishing_approve", result="success", user_id=approver_user_id,
        channel_id=run.channel_id, after_state={"state": run.state.value, "scheduled_at": str(run.scheduled_at)},
    )
    return run


async def cancel_run(db: AsyncSession, run: PublishingRun, user_id: uuid.UUID) -> PublishingRun:
    """Only reversible before an upload has actually started -- once
    bytes are in flight (UPLOAD_QUEUED or later) cancelling here would
    desync CreatorOS's state from what YouTube is actually doing."""
    if run.state not in (PublishingState.DRAFT, PublishingState.READY, PublishingState.SCHEDULED):
        raise ConflictError(f"Cannot cancel a run in state {run.state.value}")
    run.state = PublishingState.CANCELLED
    run.cancelled_by_user_id = user_id
    run.cancelled_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(run)
    await audit_service.record(
        db, action_type="publishing_cancel", result="success", user_id=user_id, channel_id=run.channel_id,
    )
    return run


async def reschedule_run(
    db: AsyncSession, run: PublishingRun, user_id: uuid.UUID, new_scheduled_at: datetime | None
) -> PublishingRun:
    if run.state not in (PublishingState.DRAFT, PublishingState.READY, PublishingState.SCHEDULED):
        raise ConflictError(f"Cannot reschedule a run in state {run.state.value}")
    run.scheduled_at = new_scheduled_at
    if not run.requires_approval:
        # Already approved -- re-apply the same immediate-vs-scheduled
        # rule approve_run uses, since the schedule just changed.
        if new_scheduled_at and ensure_aware(new_scheduled_at) > datetime.now(UTC):
            run.state = PublishingState.SCHEDULED
        else:
            run.state = PublishingState.READY
    await db.commit()
    await db.refresh(run)
    await audit_service.record(
        db, action_type="publishing_reschedule", result="success", user_id=user_id,
        channel_id=run.channel_id, after_state={"scheduled_at": str(new_scheduled_at)},
    )
    return run


async def claim_due_scheduled_run_ids(db: AsyncSession) -> list[uuid.UUID]:
    """Atomically claims every SCHEDULED run whose scheduled_at has
    passed, transitioning each to READY in one UPDATE ... WHERE state
    check per row so two overlapping poll ticks (or poll workers) can
    never both claim -- and therefore never both execute -- the same
    run. Returns the claimed ids for the caller to dispatch execution
    for, one Celery task per run (so a slow/failing upload never blocks
    the rest of the batch)."""
    from sqlalchemy import update

    now = datetime.now(UTC)
    due_ids = list(
        await db.scalars(
            select(PublishingRun.id).where(
                PublishingRun.state == PublishingState.SCHEDULED,
                PublishingRun.scheduled_at <= now,
            )
        )
    )
    claimed: list[uuid.UUID] = []
    for run_id in due_ids:
        result = await db.execute(
            update(PublishingRun)
            .where(PublishingRun.id == run_id, PublishingRun.state == PublishingState.SCHEDULED)
            .values(state=PublishingState.READY)
        )
        if result.rowcount == 1:
            claimed.append(run_id)
    await db.commit()
    return claimed


async def execute_run(db: AsyncSession, run: PublishingRun) -> tuple[PublishingRun, str]:
    """Steps 10-13 of the safety gate's own docstring promise, which nothing
    in the repo ever implemented (confirmed by the production audit: a run
    could reach READY and never progress further). Returns (run, result)
    where result is one of: succeeded | processing | failed |
    configuration_required | blocked.

    Never fabricates success. A run with no real video file to upload is
    refused with configuration_required, not silently marked published --
    CreatorOS has no video-upload/content-factory pipeline yet producing
    files for this to send (see docs/). Whenever a real file IS provided,
    this performs a genuine upload through the same YouTubeProvider
    interface OAuth/sync already use -- no separate, parallel integration.
    """
    if run.state != PublishingState.READY:
        return run, "blocked"

    # Re-check the gate at execution time, not just at approval time --
    # state (kill switch, daily limit, rule expiry) can change in between.
    passed, checks, block_reason = await run_safety_gate(db, run)
    if not passed:
        run.state = PublishingState.FAILED
        run.failure_reason = f"Safety gate failed at execution time: {block_reason}"
        await db.commit()
        await record_attempt(db, run, False, checks, "blocked", run.failure_reason)
        return run, "blocked"

    run.state = PublishingState.VALIDATING
    await db.commit()

    video_file_path = None
    if run.video_media_asset_id:
        from app.modules.media.models import MediaAsset
        from app.modules.media.service import local_path_for

        asset = await db.get(MediaAsset, run.video_media_asset_id)
        # Re-verify ownership here too, not just at upload/create time --
        # defense in depth against a run somehow referencing another
        # user's asset id.
        if asset and asset.owner_user_id == run.owner_user_id:
            video_file_path = local_path_for(asset)

    if not video_file_path or not os.path.isfile(video_file_path):
        run.state = PublishingState.FAILED
        run.failure_reason = (
            "CONFIGURATION_REQUIRED: no source video file available to upload -- "
            "upload one via POST /media/upload and reference it as media_asset_id"
        )
        await db.commit()
        await record_attempt(db, run, True, checks, "configuration_required", run.failure_reason)
        return run, "configuration_required"

    ext = os.path.splitext(video_file_path)[1].lower()
    if ext not in _ALLOWED_VIDEO_EXTENSIONS:
        run.state = PublishingState.FAILED
        run.failure_reason = f"Rejected file type '{ext}' -- allowed: {sorted(_ALLOWED_VIDEO_EXTENSIONS)}"
        await db.commit()
        await record_attempt(db, run, True, checks, "failed", run.failure_reason)
        return run, "failed"

    file_size = os.path.getsize(video_file_path)
    if file_size == 0 or file_size > _MAX_UPLOAD_BYTES:
        run.state = PublishingState.FAILED
        run.failure_reason = f"Rejected file size {file_size} bytes"
        await db.commit()
        await record_attempt(db, run, True, checks, "failed", run.failure_reason)
        return run, "failed"

    channel = await db.get(Channel, run.channel_id)
    metadata = json.loads(run.metadata_json) if run.metadata_json else {}

    try:
        access_token = await _get_valid_access_token(db, channel)
        if not access_token:
            raise YouTubeProviderError("Channel has no valid OAuth access token")

        provider = get_youtube_provider()
        run.state = PublishingState.UPLOAD_QUEUED
        await db.commit()

        upload_metadata = UploadMetadata(
            title=metadata.get("title", "")[:100],
            description=metadata.get("description", ""),
            tags=metadata.get("tags", []),
            category_id=metadata.get("category_id", "22"),
            privacy_status=metadata.get("privacy_status", "private"),
        )
        session = await provider.prepare_upload(access_token, upload_metadata, file_size)

        run.state = PublishingState.UPLOADING
        await db.commit()
        result = await provider.upload_video(
            session, video_file_path, _ALLOWED_VIDEO_EXTENSIONS[ext]
        )
        run.youtube_video_id = result.youtube_video_id

        thumbnail_path = metadata.get("thumbnail_path")
        if thumbnail_path and os.path.isfile(thumbnail_path):
            try:
                await provider.set_thumbnail(access_token, result.youtube_video_id, thumbnail_path)
            except YouTubeProviderError as exc:
                # Best-effort: a thumbnail failure must never fail an
                # otherwise-successful upload.
                logger.warning(
                    "publishing_thumbnail_set_failed", run_id=str(run.id), error=str(exc)
                )

        run.state = PublishingState.PROCESSING
        await db.commit()

        is_live = await provider.verify_publication(result.youtube_video_id)
    except YouTubeProviderError as exc:
        run.state = PublishingState.FAILED
        run.failure_reason = str(exc)
        await db.commit()
        await record_attempt(db, run, True, checks, "failed", str(exc))
        return run, "failed"

    if is_live:
        run.state = PublishingState.PUBLISHED
        run.published_url = f"https://www.youtube.com/watch?v={run.youtube_video_id}"
        run.published_at = datetime.now(UTC)
        await db.commit()
        await record_attempt(db, run, True, checks, "succeeded", None)
        return run, "succeeded"

    # Uploaded, but not yet publicly verifiable -- honest intermediate
    # state, never a fabricated PUBLISHED. A follow-up check (poll_pending_
    # publishing_runs) will finalize this once YouTube finishes processing.
    await db.commit()
    await record_attempt(db, run, True, checks, "processing", None)
    return run, "processing"


async def poll_pending_publishing_runs(db: AsyncSession) -> int:
    """Finalizes PROCESSING runs whose video has since become publicly
    verifiable. Returns the number transitioned to PUBLISHED."""
    pending = list(
        await db.scalars(select(PublishingRun).where(PublishingRun.state == PublishingState.PROCESSING))
    )
    transitioned = 0
    for run in pending:
        if not run.youtube_video_id:
            continue
        provider = get_youtube_provider()
        try:
            is_live = await provider.verify_publication(run.youtube_video_id)
        except YouTubeProviderError as exc:
            logger.warning("publishing_poll_failed", run_id=str(run.id), error=str(exc))
            continue
        if is_live:
            run.state = PublishingState.PUBLISHED
            run.published_url = f"https://www.youtube.com/watch?v={run.youtube_video_id}"
            run.published_at = datetime.now(UTC)
            await db.commit()
            transitioned += 1
    return transitioned


async def list_runs(db: AsyncSession, owner_user_id: uuid.UUID) -> list[PublishingRun]:
    result = await db.scalars(
        select(PublishingRun)
        .where(PublishingRun.owner_user_id == owner_user_id)
        .order_by(PublishingRun.created_at.desc())
    )
    return list(result)
