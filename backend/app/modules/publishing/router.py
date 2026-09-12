import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crud import get_owned_or_404
from app.db.session import get_db
from app.modules.auth.dependencies import get_current_user, require_editor
from app.modules.channels.models import Channel
from app.modules.publishing import service
from app.modules.publishing.models import PublishingRun
from app.modules.publishing.schemas import (
    CreatePublishingRunRequest,
    PublishingRuleOut,
    PublishingRunOut,
    SafetyGateResultOut,
    UpdatePublishingRuleRequest,
)
from app.modules.users.models import User

router = APIRouter()


@router.get("/rules/{channel_id}", response_model=PublishingRuleOut)
async def get_rule(
    channel_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    await get_owned_or_404(db, Channel, channel_id, user.id)
    return await service.get_or_create_rule(db, user.id, channel_id)


@router.patch("/rules/{channel_id}", response_model=PublishingRuleOut)
async def update_rule(
    channel_id: uuid.UUID,
    payload: UpdatePublishingRuleRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    await get_owned_or_404(db, Channel, channel_id, user.id)
    rule = await service.get_or_create_rule(db, user.id, channel_id)
    return await service.update_rule(db, rule, **payload.model_dump(exclude_none=True))


@router.get("/runs", response_model=list[PublishingRunOut])
async def list_runs(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await service.list_runs(db, user.id)


@router.post("/runs", response_model=PublishingRunOut, status_code=201)
async def create_run(
    payload: CreatePublishingRunRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_editor),
):
    await get_owned_or_404(db, Channel, payload.channel_id, user.id)
    metadata = payload.model_dump(exclude={"channel_id", "content_item_id", "mode", "idempotency_key"})
    return await service.create_run(
        db, user.id, payload.channel_id, payload.content_item_id, payload.mode, metadata, payload.idempotency_key
    )


@router.post("/runs/{run_id}/gate-check", response_model=SafetyGateResultOut)
async def gate_check(
    run_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_editor)
):
    run = await get_owned_or_404(db, PublishingRun, run_id, user.id)
    passed, checks, reason = await service.run_safety_gate(db, run)
    await service.record_attempt(
        db, run, passed, checks, "blocked" if not passed else "gate_passed", reason
    )
    return SafetyGateResultOut(passed=passed, checks=checks, block_reason=reason)


@router.post("/runs/{run_id}/approve", response_model=PublishingRunOut)
async def approve_run(
    run_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_editor)
):
    run = await get_owned_or_404(db, PublishingRun, run_id, user.id)
    return await service.approve_run(db, run, user.id)
