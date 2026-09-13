"""Growth experiments (A/B). A winner is only declared once every variant has
reached the experiment's minimum_sample_size — never on vibes."""
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.data_quality import Confidence
from app.core.errors import ConflictError, NotFoundError
from app.modules.experiments import learning
from app.modules.experiments.measurement import PROPORTION_METRICS, measure_video_metric
from app.modules.experiments.models import Experiment, ExperimentStatus, ExperimentVariant
from app.modules.experiments.statistics import confidence_from_p_value, two_proportion_z_test


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


async def get_owned_variant(db: AsyncSession, variant_id: uuid.UUID, owner_user_id: uuid.UUID) -> ExperimentVariant:
    """ExperimentVariant has no owner column of its own -- ownership
    flows through its parent Experiment. (The original record_result
    endpoint predating this fix loaded a variant with no ownership check
    at all -- any authenticated user could record a result, and thereby
    conclude a winner, for someone else's experiment.)"""
    variant = await db.scalar(
        select(ExperimentVariant)
        .join(Experiment, Experiment.id == ExperimentVariant.experiment_id)
        .where(ExperimentVariant.id == variant_id, Experiment.owner_user_id == owner_user_id)
    )
    if not variant:
        raise NotFoundError("Experiment variant not found")
    return variant


async def link_variant_video(db: AsyncSession, variant: ExperimentVariant, video_id: uuid.UUID) -> ExperimentVariant:
    """Links a variant to the real published video its performance
    should be measured from -- required before measure_variant() can
    pull anything."""
    variant.video_id = video_id
    await db.commit()
    await db.refresh(variant)
    return variant


async def measure_variant(db: AsyncSession, variant: ExperimentVariant) -> tuple[ExperimentVariant, str]:
    """Automated measurement: pulls the real metric from the variant's
    linked video instead of a human typing in a number. Returns (variant,
    status) where status is 'measured' or 'insufficient_data' -- never
    silently leaves a fabricated value."""
    if not variant.video_id:
        raise ConflictError(
            "Variant has no linked video -- call link_variant_video first, or use manual "
            "record_variant_result for a metric YouTube's API doesn't expose"
        )
    experiment = await get_experiment(db, variant.experiment_id)
    result = await measure_video_metric(db, variant.video_id, experiment.metric)
    if result.quality == "INSUFFICIENT_DATA":
        return variant, "insufficient_data"

    variant.metric_value = result.metric_value
    variant.sample_size = result.sample_size
    variant.measured_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(variant)

    experiment = await get_experiment(db, variant.experiment_id)
    await _maybe_conclude(db, experiment)
    return variant, "measured"


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

    if experiment.metric in PROPORTION_METRICS and winner.id != control.id:
        # Real statistical test: a two-proportion z-test on the actual
        # observed rates/sample sizes, not a "lift > 20%" guess.
        _, p_value = two_proportion_z_test(
            winner.metric_value or 0, winner.sample_size, control.metric_value or 0, control.sample_size
        )
        confidence = confidence_from_p_value(p_value)
    else:
        # No stored variance for count/duration metrics (views,
        # avg_view_duration, subscribers_gained) -- a real z/t-test needs
        # it. Documented heuristic fallback rather than a false claim of
        # statistical precision this data can't support.
        lift = (
            ((winner.metric_value or 0) - (control.metric_value or 0)) / control.metric_value
            if control.metric_value
            else 0
        )
        confidence = (
            Confidence.HIGH.value
            if abs(lift) > 0.2
            else Confidence.MEDIUM.value
            if abs(lift) > 0.05
            else Confidence.LOW.value
        )

    experiment.status = ExperimentStatus.COMPLETED
    experiment.ended_at = datetime.now(UTC)
    experiment.winning_variant_id = winner.id
    experiment.confidence = confidence
    await db.commit()
    # expire_on_commit=False (see AsyncSessionLocal) means experiment.variants
    # and the just-set winning_variant_id are still populated here -- no
    # extra round-trip needed before handing this off to the learning loop.
    await learning.record_experiment_outcome(db, experiment)
