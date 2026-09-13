import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crud import get_owned_or_404
from app.db.session import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.experiments import service
from app.modules.experiments.models import Experiment
from app.modules.experiments.schemas import (
    CreateExperimentRequest,
    ExperimentOut,
    LinkVariantVideoRequest,
    MeasureVariantResultOut,
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
    """Manual fallback for a metric YouTube's API doesn't expose. Prefer
    POST /variants/{id}/measure whenever a video is linked -- that pulls
    the real number automatically instead of trusting a typed-in one."""
    variant = await service.get_owned_variant(db, variant_id, user.id)
    return await service.record_variant_result(
        db, variant, payload.sample_size, payload.metric_value
    )


@router.post("/variants/{variant_id}/link-video", response_model=VariantOut)
async def link_variant_video(
    variant_id: uuid.UUID,
    payload: LinkVariantVideoRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    variant = await service.get_owned_variant(db, variant_id, user.id)
    return await service.link_variant_video(db, variant, payload.video_id)


@router.post("/variants/{variant_id}/measure", response_model=MeasureVariantResultOut)
async def measure_variant(
    variant_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """Automated measurement: pulls the real metric from the variant's
    linked video's synced analytics. Returns insufficient_data (never a
    fabricated number) if nothing real has synced yet."""
    variant = await service.get_owned_variant(db, variant_id, user.id)
    variant, status = await service.measure_variant(db, variant)
    return MeasureVariantResultOut(variant=variant, status=status)
