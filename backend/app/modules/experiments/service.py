"""Growth experiments (A/B). A winner is only declared once every variant has
reached the experiment's minimum_sample_size — never on vibes."""
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.data_quality import Confidence
from app.modules.experiments.models import Experiment, ExperimentStatus, ExperimentVariant


async def create_experiment(
    db: AsyncSession,
    owner_user_id: uuid.UUID,
    experiment_type: str,
    hypothesis: str,
    metric: str,
    video_id: uuid.UUID | None,
    minimum_sample_size: int,
    variant_contents: list[str],
) -> Experiment:
    experiment = Experiment(
        owner_user_id=owner_user_id,
        video_id=video_id,
        experiment_type=experiment_type,
        hypothesis=hypothesis,
        metric=metric,
        minimum_sample_size=minimum_sample_size,
        status=ExperimentStatus.DRAFT,
    )
    db.add(experiment)
    await db.flush()

    labels = ["control"] + [f"variant_{chr(97 + i)}" for i in range(len(variant_contents) - 1)]
    for label, content in zip(labels, variant_contents, strict=True):
        db.add(ExperimentVariant(experiment_id=experiment.id, label=label, content=content))

    await db.commit()
    return await get_experiment(db, experiment.id)


async def get_experiment(db: AsyncSession, experiment_id: uuid.UUID) -> Experiment | None:
    return await db.scalar(
        select(Experiment)
        .where(Experiment.id == experiment_id)
        .options(selectinload(Experiment.variants))
    )


async def list_experiments(db: AsyncSession, owner_user_id: uuid.UUID) -> list[Experiment]:
    result = await db.scalars(
        select(Experiment)
        .where(Experiment.owner_user_id == owner_user_id)
        .options(selectinload(Experiment.variants))
        .order_by(Experiment.created_at.desc())
    )
    return list(result)


async def start_experiment(db: AsyncSession, experiment: Experiment) -> Experiment:
    experiment.status = ExperimentStatus.RUNNING
    experiment.started_at = datetime.now(UTC)
    await db.commit()
    return await get_experiment(db, experiment.id)


async def record_variant_result(
    db: AsyncSession, variant: ExperimentVariant, sample_size: int, metric_value: float
) -> ExperimentVariant:
    variant.sample_size = sample_size
    variant.metric_value = metric_value
    await db.commit()
    await db.refresh(variant)

    experiment = await get_experiment(db, variant.experiment_id)
    await _maybe_conclude(db, experiment)
    return variant


async def _maybe_conclude(db: AsyncSession, experiment: Experiment) -> None:
    if experiment.status != ExperimentStatus.RUNNING:
        return
    if not experiment.variants or any(
        v.sample_size < experiment.minimum_sample_size for v in experiment.variants
    ):
        return

    winner = max(experiment.variants, key=lambda v: v.metric_value or 0)
    control = next((v for v in experiment.variants if v.label == "control"), experiment.variants[0])
    lift = (
        ((winner.metric_value or 0) - (control.metric_value or 0)) / control.metric_value
        if control.metric_value
        else 0
    )

    experiment.status = ExperimentStatus.COMPLETED
    experiment.ended_at = datetime.now(UTC)
    experiment.winning_variant_id = winner.id
    experiment.confidence = (
        Confidence.HIGH.value
        if abs(lift) > 0.2
        else Confidence.MEDIUM.value
        if abs(lift) > 0.05
        else Confidence.LOW.value
    )
    await db.commit()
