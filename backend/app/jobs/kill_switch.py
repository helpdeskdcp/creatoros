"""Growth OS emergency stop. Every autonomous task must call is_active()
before starting NEW work — it never cancels work already in flight and never
deletes data (see docs/operations.md: Kill Switch)."""
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.models import KillSwitch
from app.modules.audit import service as audit_service


async def get_or_create(db: AsyncSession, owner_user_id: uuid.UUID) -> KillSwitch:
    switch = await db.scalar(select(KillSwitch).where(KillSwitch.owner_user_id == owner_user_id))
    if not switch:
        switch = KillSwitch(owner_user_id=owner_user_id, is_active=False)
        db.add(switch)
        await db.commit()
        await db.refresh(switch)
    return switch


async def is_active(db: AsyncSession, owner_user_id: uuid.UUID) -> bool:
    switch = await db.scalar(select(KillSwitch).where(KillSwitch.owner_user_id == owner_user_id))
    return bool(switch and switch.is_active)


async def activate(db: AsyncSession, owner_user_id: uuid.UUID, reason: str | None) -> KillSwitch:
    switch = await get_or_create(db, owner_user_id)
    switch.is_active = True
    switch.activated_at = datetime.now(UTC)
    switch.reason = reason
    await db.commit()
    await db.refresh(switch)
    await audit_service.record(
        db, action_type="kill_switch_activate", result="success", user_id=owner_user_id,
        after_state={"reason": reason},
    )
    return switch


async def deactivate(db: AsyncSession, owner_user_id: uuid.UUID) -> KillSwitch:
    switch = await get_or_create(db, owner_user_id)
    switch.is_active = False
    switch.activated_at = None
    switch.reason = None
    await db.commit()
    await db.refresh(switch)
    await audit_service.record(
        db, action_type="kill_switch_deactivate", result="success", user_id=owner_user_id,
    )
    return switch
