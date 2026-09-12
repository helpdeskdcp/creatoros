"""Append-only audit logging. record() is the ONLY way anything in CreatorOS
should write to audit_logs — it actively scrubs anything that looks like a
secret so a careless caller can't leak one into the log."""
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog

_SECRET_KEY_PATTERN = re.compile(
    r"(token|secret|password|api_key|apikey|authorization|refresh_token|access_token)", re.IGNORECASE
)


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("***REDACTED***" if _SECRET_KEY_PATTERN.search(k) else _scrub(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


async def record(
    db: AsyncSession,
    *,
    action_type: str,
    result: str,
    user_id: uuid.UUID | None = None,
    channel_id: uuid.UUID | None = None,
    provider: str | None = None,
    content_id: str | None = None,
    campaign_id: uuid.UUID | None = None,
    request_id: str | None = None,
    authorization_state: str | None = None,
    rule_set: dict | None = None,
    failure_reason: str | None = None,
    before_state: dict | None = None,
    after_state: dict | None = None,
) -> AuditLog:
    entry = AuditLog(
        created_at=datetime.now(UTC),
        user_id=user_id,
        channel_id=channel_id,
        action_type=action_type,
        provider=provider,
        content_id=content_id,
        campaign_id=campaign_id,
        request_id=request_id,
        authorization_state=authorization_state,
        rule_set_json=json.dumps(_scrub(rule_set)) if rule_set else None,
        result=result,
        failure_reason=failure_reason,
        before_state_json=json.dumps(_scrub(before_state)) if before_state else None,
        after_state_json=json.dumps(_scrub(after_state)) if after_state else None,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


async def list_logs(
    db: AsyncSession, user_id: uuid.UUID | None = None, action_type: str | None = None, limit: int = 100
) -> list[AuditLog]:
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if action_type:
        stmt = stmt.where(AuditLog.action_type == action_type)
    return list(await db.scalars(stmt))
