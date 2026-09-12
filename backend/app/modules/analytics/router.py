import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crud import get_owned_or_404
from app.db.session import get_db
from app.modules.analytics import service
from app.modules.analytics.schemas import (
    GrowthDiagnosisOut,
    GrowthScorecardOut,
    SnapshotOut,
    SubscriberGrowthOut,
)
from app.modules.auth.dependencies import get_current_user
from app.modules.channels.models import Channel
from app.modules.users.models import User

router = APIRouter()


@router.get("/channel/{channel_id}/snapshots", response_model=list[SnapshotOut])
async def list_snapshots(
    channel_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    await get_owned_or_404(db, Channel, channel_id, user.id)
    return await service.list_snapshots(db, channel_id)


@router.post("/channel/{channel_id}/snapshots", response_model=SnapshotOut, status_code=201)
async def take_snapshot(
    channel_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    channel = await get_owned_or_404(db, Channel, channel_id, user.id)
    return await service.take_snapshot(db, channel)


@router.get("/growth/{channel_id}/scorecard", response_model=GrowthScorecardOut)
async def growth_scorecard(
    channel_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    channel = await get_owned_or_404(db, Channel, channel_id, user.id)
    return await service.compute_growth_scorecard(db, channel)


@router.get("/growth/{channel_id}/diagnosis", response_model=GrowthDiagnosisOut)
async def growth_diagnosis(
    channel_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    channel = await get_owned_or_404(db, Channel, channel_id, user.id)
    return await service.diagnose_growth(db, channel)


@router.get("/growth/{channel_id}/subscribers", response_model=SubscriberGrowthOut)
async def subscriber_growth(
    channel_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    channel = await get_owned_or_404(db, Channel, channel_id, user.id)
    return await service.compute_subscriber_growth(db, channel)
