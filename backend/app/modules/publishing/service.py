"""Publishing safety gate + state machine. Extends Channel/YouTubeProvider —
this module owns authorization/rules/idempotency; app.modules.channels.providers
still owns the actual YouTube API calls.

Every automated publish passes through run_safety_gate() before any upload
call is made. A failed gate blocks the action (BLOCK_ACTION) and is always
recorded, win or lose, in publishing_attempts + audit_logs.
"""
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutils import ensure_aware
from app.jobs import kill_switch
from app.modules.audit import service as audit_service
from app.modules.channels.models import Channel
from app.modules.publishing.models import (
    PublishingAttempt,
    PublishingMode,
    PublishingRule,
    PublishingRun,
    PublishingState,
)


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
    run.state = PublishingState.READY
    await db.commit()
    await db.refresh(run)
    return run


async def list_runs(db: AsyncSession, owner_user_id: uuid.UUID) -> list[PublishingRun]:
    result = await db.scalars(
        select(PublishingRun)
        .where(PublishingRun.owner_user_id == owner_user_id)
        .order_by(PublishingRun.created_at.desc())
    )
    return list(result)
