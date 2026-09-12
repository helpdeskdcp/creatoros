"""Autonomous Control Center: kill switch + a rollup of automation state.
Reuses channels/publishing/jobs — no parallel automation-state system."""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.jobs import kill_switch
from app.modules.auth.dependencies import get_current_user, require_admin
from app.modules.channels.models import Channel
from app.modules.publishing.models import PublishingRule, PublishingRun, PublishingState
from app.modules.settings.schemas import (
    ActivateKillSwitchRequest,
    ControlCenterOut,
    KillSwitchOut,
)
from app.modules.users.models import User

router = APIRouter()


@router.get("/kill-switch", response_model=KillSwitchOut)
async def get_kill_switch(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    switch = await kill_switch.get_or_create(db, user.id)
    return switch


@router.post("/kill-switch/activate", response_model=KillSwitchOut)
async def activate_kill_switch(
    payload: ActivateKillSwitchRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Emergency stop: blocks all NEW autonomous publishing/distribution
    actions. Never cancels in-flight work and never deletes data."""
    return await kill_switch.activate(db, user.id, payload.reason)


@router.post("/kill-switch/deactivate", response_model=KillSwitchOut)
async def deactivate_kill_switch(
    db: AsyncSession = Depends(get_db), user: User = Depends(require_admin)
):
    return await kill_switch.deactivate(db, user.id)


@router.get("/control-center", response_model=ControlCenterOut)
async def control_center(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    switch = await kill_switch.get_or_create(db, user.id)

    connected_channels = await db.scalar(
        select(func.count()).select_from(Channel).where(Channel.owner_user_id == user.id)
    )
    active_rules = await db.scalar(
        select(func.count()).select_from(PublishingRule).where(
            PublishingRule.owner_user_id == user.id, PublishingRule.is_enabled.is_(True)
        )
    )
    pending_runs = await db.scalar(
        select(func.count()).select_from(PublishingRun).where(
            PublishingRun.owner_user_id == user.id, PublishingRun.requires_approval.is_(True)
        )
    )
    completed_runs = await db.scalar(
        select(func.count()).select_from(PublishingRun).where(
            PublishingRun.owner_user_id == user.id, PublishingRun.state == PublishingState.PUBLISHED
        )
    )
    failed_runs = await db.scalar(
        select(func.count()).select_from(PublishingRun).where(
            PublishingRun.owner_user_id == user.id, PublishingRun.state == PublishingState.FAILED
        )
    )

    return ControlCenterOut(
        kill_switch=KillSwitchOut.model_validate(switch, from_attributes=True),
        connected_channels=connected_channels or 0,
        active_publishing_rules=active_rules or 0,
        pending_runs=pending_runs or 0,
        completed_runs=completed_runs or 0,
        failed_runs=failed_runs or 0,
    )
