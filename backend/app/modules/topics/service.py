"""Topic Opportunity Engine. Every score traces back to a Trend row (itself
derived from real creator/competitor video data) — a topic with no linked
trend or insufficient underlying sample size returns INSUFFICIENT_DATA
rather than an invented level."""
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_quality import MIN_SAMPLE_SIZE_TREND
from app.modules.topics.models import Opportunity, OpportunityLevel, Topic
from app.modules.trends.models import Trend


async def create_topic(
    db: AsyncSession,
    owner_user_id: uuid.UUID,
    title: str,
    description: str | None,
    trend_id: uuid.UUID | None,
) -> Topic:
    topic = Topic(
        owner_user_id=owner_user_id, title=title, description=description, trend_id=trend_id
    )
    db.add(topic)
    await db.commit()
    await db.refresh(topic)
    return topic


async def list_topics(db: AsyncSession, owner_user_id: uuid.UUID) -> list[Topic]:
    result = await db.scalars(
        select(Topic).where(Topic.owner_user_id == owner_user_id).order_by(Topic.created_at.desc())
    )
    return list(result)


async def compute_opportunity(db: AsyncSession, topic: Topic) -> Opportunity:
    now = datetime.now(UTC)

    trend = await db.get(Trend, topic.trend_id) if topic.trend_id else None
    if not trend or trend.sample_size < MIN_SAMPLE_SIZE_TREND:
        opportunity = Opportunity(
            topic_id=topic.id,
            level=OpportunityLevel.INSUFFICIENT_DATA,
            sample_size=trend.sample_size if trend else 0,
            explanation=(
                "This topic is not linked to a trend with enough underlying video "
                f"data (needs at least {MIN_SAMPLE_SIZE_TREND} tracked videos)."
            ),
            computed_at=now,
        )
        db.add(opportunity)
        await db.commit()
        await db.refresh(opportunity)
        return opportunity

    audience_demand = trend.audience_fit_score or 0.0
    momentum = trend.growth_score or 0.0
    competition = trend.competition_score or 0.0
    creator_fit = trend.creator_fit_score or 0.0
    historical_performance = trend.creator_fit_score or 0.0
    content_gap = trend.content_gap_score or 0.0
    freshness = trend.timeliness_score or 0.0

    composite = (
        0.2 * audience_demand
        + 0.2 * momentum
        + 0.15 * creator_fit
        + 0.15 * historical_performance
        + 0.2 * content_gap
        + 0.1 * freshness
    ) - (0.1 * competition)

    if composite >= 65:
        level = OpportunityLevel.HIGH
    elif composite >= 40:
        level = OpportunityLevel.MEDIUM
    else:
        level = OpportunityLevel.LOW

    explanation = (
        f"Composite opportunity score {composite:.1f}/100 from trend '{trend.keyword}' "
        f"(sample size {trend.sample_size}): audience demand {audience_demand:.0f}, "
        f"momentum {momentum:.0f}, competition {competition:.0f}, creator fit {creator_fit:.0f}, "
        f"content gap {content_gap:.0f}, freshness {freshness:.0f}."
    )

    opportunity = Opportunity(
        topic_id=topic.id,
        audience_demand_score=audience_demand,
        momentum_score=momentum,
        competition_score=competition,
        creator_fit_score=creator_fit,
        historical_performance_score=historical_performance,
        content_gap_score=content_gap,
        freshness_score=freshness,
        level=level,
        sample_size=trend.sample_size,
        explanation=explanation,
        computed_at=now,
    )
    db.add(opportunity)
    await db.commit()
    await db.refresh(opportunity)
    return opportunity
