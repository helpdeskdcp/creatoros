import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crud import get_owned_or_404
from app.core.errors import NotFoundError
from app.db.session import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.channels.models import Channel
from app.modules.predictions import service
from app.modules.predictions.models import PredictionMetric, PredictionRecord
from app.modules.predictions.schemas import (
    CalibrationBucketOut,
    PredictionRecordOut,
    PredictSubscriberThresholdRequest,
    PredictVideoThresholdRequest,
    RecordOutcomeRequest,
)
from app.modules.users.models import User
from app.modules.video_updates.service import get_owned_video

router = APIRouter()


@router.get("", response_model=list[PredictionRecordOut])
async def list_predictions(
    channel_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    stmt = select(PredictionRecord).where(PredictionRecord.owner_user_id == user.id)
    if channel_id is not None:
        stmt = stmt.where(PredictionRecord.channel_id == channel_id)
    stmt = stmt.order_by(PredictionRecord.created_at.desc())
    return list(await db.scalars(stmt))


@router.get("/calibration", response_model=list[CalibrationBucketOut])
async def calibration_report(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await service.get_calibration_report(db, user.id)


@router.post("/channels/{channel_id}/next-video/views", response_model=PredictionRecordOut, status_code=201)
async def predict_next_video_views(
    channel_id: uuid.UUID,
    payload: PredictVideoThresholdRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    channel = await get_owned_or_404(db, Channel, channel_id, user.id)
    return await service.predict_video_threshold_probability(
        db, channel, PredictionMetric.VIEWS, payload.threshold, payload.horizon_days,
    )


@router.post(
    "/channels/{channel_id}/videos/{video_id}/views", response_model=PredictionRecordOut, status_code=201
)
async def predict_existing_video_views(
    channel_id: uuid.UUID,
    video_id: uuid.UUID,
    payload: PredictVideoThresholdRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    channel = await get_owned_or_404(db, Channel, channel_id, user.id)
    await get_owned_video(db, video_id, user.id)  # 404s if not owned/found
    return await service.predict_video_threshold_probability(
        db, channel, PredictionMetric.VIEWS, payload.threshold, payload.horizon_days,
        exclude_video_id=video_id,
    )


@router.post("/channels/{channel_id}/subscribers", response_model=PredictionRecordOut, status_code=201)
async def predict_subscriber_gain(
    channel_id: uuid.UUID,
    payload: PredictSubscriberThresholdRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    channel = await get_owned_or_404(db, Channel, channel_id, user.id)
    return await service.predict_subscriber_gain_probability(db, channel, payload.threshold, payload.horizon_days)


@router.post("/{prediction_id}/outcome", response_model=PredictionRecordOut)
async def record_outcome(
    prediction_id: uuid.UUID,
    payload: RecordOutcomeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    record = await db.scalar(
        select(PredictionRecord).where(
            PredictionRecord.id == prediction_id, PredictionRecord.owner_user_id == user.id
        )
    )
    if not record:
        raise NotFoundError("Prediction not found")
    return await service.record_actual_outcome(db, prediction_id, payload.actual_value)
