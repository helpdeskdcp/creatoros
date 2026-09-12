"""Trend detection from real, already-stored signals: the creator's own
video history and tracked competitors' video history. Every score is a
deterministic function of observed data with an explanation string — this is
NOT an LLM guessing trend numbers (see docs/ai.md: AI never controls
analytics numbers directly)."""
import uuid
from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_quality import MIN_SAMPLE_SIZE_TREND
from app.core.text import extract_keywords
from app.modules.channels.models import Channel
from app.modules.competitors.models import Competitor, CompetitorVideo
from app.modules.trends.models import Trend, TrendSource
from app.modules.videos.models import Video


def _normalize(value: float, max_value: float) -> float:
    if max_value <= 0:
        return 0.0
    return round(min(value / max_value, 1.0) * 100, 1)


async def refresh_trends(db: AsyncSession, owner_user_id: uuid.UUID) -> list[Trend]:
    now = datetime.now(UTC)

    channel_ids = list(
        await db.scalars(select(Channel.id).where(Channel.owner_user_id == owner_user_id))
    )
    own_videos = (
        list(await db.scalars(select(Video).where(Video.channel_id.in_(channel_ids))))
        if channel_ids
        else []
    )

    competitor_ids = list(
        await db.scalars(select(Competitor.id).where(Competitor.owner_user_id == owner_user_id))
    )
    comp_videos = (
        list(
            await db.scalars(
                select(CompetitorVideo).where(CompetitorVideo.competitor_id.in_(competitor_ids))
            )
        )
        if competitor_ids
        else []
    )

    keyword_own_views: dict[str, int] = Counter()
    keyword_own_count: dict[str, int] = Counter()
    for v in own_videos:
        if v.view_count is None:
            continue
        for kw in extract_keywords(v.title):
            keyword_own_views[kw] += v.view_count
            keyword_own_count[kw] += 1

    keyword_comp_views: dict[str, int] = Counter()
    keyword_comp_count: dict[str, int] = Counter()
    for v in comp_videos:
        if v.view_count is None:
            continue
        for kw in extract_keywords(v.title):
            keyword_comp_views[kw] += v.view_count
            keyword_comp_count[kw] += 1

    all_keywords = set(keyword_own_views) | set(keyword_comp_views)
    if not all_keywords:
        return []

    max_own_views = max(keyword_own_views.values(), default=0)
    max_comp_views = max(keyword_comp_views.values(), default=0)
    max_comp_count = max(keyword_comp_count.values(), default=0)

    trends: list[Trend] = []
    for kw in all_keywords:
        sample_size = keyword_own_count.get(kw, 0) + keyword_comp_count.get(kw, 0)
        if sample_size < MIN_SAMPLE_SIZE_TREND:
            continue

        creator_fit = _normalize(keyword_own_views.get(kw, 0), max_own_views)
        momentum = _normalize(keyword_comp_views.get(kw, 0), max_comp_views)
        competition = _normalize(keyword_comp_count.get(kw, 0), max_comp_count)
        content_gap = 100.0 if kw not in keyword_own_views else 0.0
        audience_fit = round((creator_fit + momentum) / 2, 1)
        timeliness = 100.0  # only "now" data is fed in; no historical decay model yet
        trend_score = round(
            0.3 * momentum + 0.2 * creator_fit + 0.2 * audience_fit + 0.3 * content_gap, 1
        )
        opportunity_score = round(
            trend_score * 0.6 + (100 - competition) * 0.2 + content_gap * 0.2, 1
        )

        source = (
            TrendSource.COMPETITOR_MOMENTUM if keyword_comp_views.get(kw) else TrendSource.CREATOR_HISTORY
        )
        explanation = (
            f"'{kw}' appears in {sample_size} tracked videos "
            f"({keyword_own_count.get(kw, 0)} of yours, {keyword_comp_count.get(kw, 0)} from "
            f"tracked competitors). Competitor views for this keyword: "
            f"{keyword_comp_views.get(kw, 0):,}. "
            + ("You have not covered this topic yet." if content_gap else "You have already covered this topic.")
        )

        existing = await db.scalar(
            select(Trend).where(Trend.owner_user_id == owner_user_id, Trend.keyword == kw)
        )
        trend = existing or Trend(owner_user_id=owner_user_id, keyword=kw)
        trend.source = source
        trend.trend_score = trend_score
        trend.growth_score = momentum
        trend.competition_score = competition
        trend.audience_fit_score = audience_fit
        trend.creator_fit_score = creator_fit
        trend.timeliness_score = timeliness
        trend.content_gap_score = content_gap
        trend.opportunity_score = opportunity_score
        trend.sample_size = sample_size
        trend.explanation = explanation
        trend.detected_at = now
        db.add(trend)
        trends.append(trend)

    await db.commit()
    for t in trends:
        await db.refresh(t)
    trends.sort(key=lambda t: t.opportunity_score or 0, reverse=True)
    return trends


async def list_trends(db: AsyncSession, owner_user_id: uuid.UUID) -> list[Trend]:
    result = await db.scalars(
        select(Trend)
        .where(Trend.owner_user_id == owner_user_id)
        .order_by(Trend.opportunity_score.desc())
    )
    return list(result)
