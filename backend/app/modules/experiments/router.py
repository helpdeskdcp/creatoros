import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crud import get_owned_or_404
from app.core.errors import NotFoundError
from app.db.session import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.experiments import service
from app.modules.experiments.models import Experiment
from app.modules.experiments.schemas import (
    CreateExperimentRequest,
    ExperimentOut,
    RecordVariantResultRequest,
    VariantOut,
)
from app.modules.users.models import User

router = APIRouter()


@router.get("", response_model=list[ExperimentOut])
async def list_experiments(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await service.list_experiments(db, user.id)


@router.post("", response_model=ExperimentOut, status_code=201)
async def create_experiment(
    payload: CreateExperimentRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await service.create_experiment(
        db,
        user.id,
        payload.experiment_type,
        payload.hypothesis,
        payload.metric,
        payload.video_id,
        payload.minimum_sample_size,
        payload.variants,
    )


@router.post("/{experiment_id}/start", response_model=ExperimentOut)
async def start_experiment(
    experiment_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    experiment = await get_owned_or_404(db, Experiment, experiment_id, user.id)
    return await service.start_experiment(db, experiment)


@router.post("/variants/{variant_id}/result", response_model=VariantOut)
async def record_result(
    variant_id: uuid.UUID,
    payload: RecordVariantResultRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.modules.experiments.models import ExperimentVariant

    variant = await db.get(ExperimentVariant, variant_id)
    if not variant:
        raise NotFoundError("Experiment variant not found")
    return await service.record_variant_result(
        db, variant, payload.sample_size, payload.metric_value
    )
