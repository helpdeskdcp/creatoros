"""Next Best Video engine. Extends the Topic Opportunity Engine's real,
data-derived scores with AI-generated creative direction (angle/hook/titles)
— the AI never invents the opportunity score itself, only the creative
framing around a topic CreatorOS has already scored from real data."""
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.cache import cached_generate
from app.ai.orchestrator import AIOrchestrator
from app.ai.router import AIMode
from app.core.data_quality import MIN_SAMPLE_SIZE_RECOMMENDATION, Confidence
from app.modules.recommendations.models import Recommendation
from app.modules.recommendations.schemas import _GeneratedRecommendationDetail
from app.modules.topics.models import Opportunity, OpportunityLevel, Topic
from app.modules.trends.models import Trend

SYSTEM_PROMPT = (
    "You are CreatorOS's Next Best Video engine. Given a topic that has "
    "already been scored as a real opportunity from the creator's own "
    "channel and competitor data, propose concrete creative direction: "
    "target audience, content angle, a hook, 3-5 title candidates, a "
    "thumbnail concept, and the best format. Score viral potential, "
    "discovery potential, subscriber potential, retention potential, and "
    "audience fit separately (0-100) — never combine them into one number. "
    "Never claim guaranteed views or subscribers."
)

_LEVEL_SCORE = {
    OpportunityLevel.HIGH: 85.0,
    OpportunityLevel.MEDIUM: 60.0,
    OpportunityLevel.LOW: 35.0,
}


async def generate_next_best_videos(
    db: AsyncSession, orchestrator: AIOrchestrator, owner_user_id: uuid.UUID, limit: int = 10
) -> list[Recommendation]:
    # Pull the most recent opportunity per topic, keep HIGH/MEDIUM only.
    topics = list(
        await db.scalars(select(Topic).where(Topic.owner_user_id == owner_user_id))
    )
    candidates: list[tuple[Topic, Opportunity, Trend | None]] = []
    for topic in topics:
        opp = await db.scalar(
            select(Opportunity)
            .where(Opportunity.topic_id == topic.id)
            .order_by(Opportunity.computed_at.desc())
        )
        if not opp or opp.level not in (OpportunityLevel.HIGH, OpportunityLevel.MEDIUM):
            continue
        trend = await db.get(Trend, topic.trend_id) if topic.trend_id else None
        candidates.append((topic, opp, trend))

    candidates.sort(key=lambda c: _LEVEL_SCORE[c[1].level], reverse=True)
    candidates = candidates[:limit]

    # Replace the previous recommendation batch — this endpoint always
    # represents "right now's" top videos, not a growing history.
    old = list(
        await db.scalars(select(Recommendation).where(Recommendation.owner_user_id == owner_user_id))
    )
    for o in old:
        await db.delete(o)
    await db.flush()

    now = datetime.now(UTC)
    recommendations: list[Recommendation] = []
    for rank, (topic, opp, trend) in enumerate(candidates, start=1):
        sample_size = trend.sample_size if trend else opp.sample_size
        confidence = (
            Confidence.HIGH
            if sample_size >= MIN_SAMPLE_SIZE_RECOMMENDATION
            else Confidence.MEDIUM
            if sample_size >= 1
            else Confidence.INSUFFICIENT_DATA
        )

        user_prompt = (
            f"Topic: {topic.title}\n"
            f"Opportunity level: {opp.level.value} ({opp.explanation})\n"
            f"Description: {topic.description or 'n/a'}"
        )
        detail: _GeneratedRecommendationDetail = await cached_generate(db, orchestrator, 
            task="next_best_video",
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            schema=_GeneratedRecommendationDetail,
            user_id=owner_user_id,
        mode=AIMode.FAST,
        )

        rec = Recommendation(
            owner_user_id=owner_user_id,
            topic_id=topic.id,
            rank=rank,
            topic=topic.title,
            format=detail.format,
            target_audience=detail.target_audience,
            content_angle=detail.content_angle,
            hook=detail.hook,
            title_candidates_json=json.dumps(detail.title_candidates),
            thumbnail_concept=detail.thumbnail_concept,
            reason=detail.reasoning,
            supporting_evidence=opp.explanation,
            opportunity_score=_LEVEL_SCORE[opp.level],
            viral_potential_score=detail.viral_potential_score,
            discovery_score=detail.discovery_score,
            subscriber_potential_score=detail.subscriber_potential_score,
            retention_potential_score=detail.retention_potential_score,
            audience_fit_score=detail.audience_fit_score,
            confidence=confidence.value,
            sample_size=sample_size,
            generated_at=now,
        )
        db.add(rec)
        recommendations.append(rec)

    await db.commit()
    for r in recommendations:
        await db.refresh(r)
    return recommendations


async def list_recommendations(db: AsyncSession, owner_user_id: uuid.UUID) -> list[Recommendation]:
    result = await db.scalars(
        select(Recommendation)
        .where(Recommendation.owner_user_id == owner_user_id)
        .order_by(Recommendation.rank)
    )
    return list(result)
