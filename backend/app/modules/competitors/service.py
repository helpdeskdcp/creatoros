"""Competitor tracking + the Competitor Opportunity Engine. Uses only public
channel/video data reached through the same YouTubeProvider interface as the
creator's own channel — never private competitor analytics."""
import uuid
from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.core.text import extract_keywords
from app.modules.channels.models import Channel
from app.modules.channels.providers import get_youtube_provider
from app.modules.competitors.models import Competitor, CompetitorVideo
from app.modules.competitors.schemas import ContentGap
from app.modules.videos.models import Video


async def add_competitor(
    db: AsyncSession, owner_user_id: uuid.UUID, youtube_channel_id: str, notes: str | None
) -> Competitor:
    existing = await db.scalar(
        select(Competitor).where(
            Competitor.owner_user_id == owner_user_id,
            Competitor.youtube_channel_id == youtube_channel_id,
        )
    )
    if existing:
        raise ConflictError("This competitor is already tracked")

    provider = get_youtube_provider()
    channel_data = await provider.get_channel(channel_id=youtube_channel_id)

    competitor = Competitor(
        owner_user_id=owner_user_id,
        youtube_channel_id=channel_data.youtube_channel_id,
        title=channel_data.title,
        thumbnail_url=channel_data.thumbnail_url,
        subscriber_count=channel_data.subscriber_count,
        view_count=channel_data.view_count,
        video_count=channel_data.video_count,
        notes=notes,
    )
    db.add(competitor)
    await db.commit()
    await db.refresh(competitor)
    return competitor


async def sync_competitor(db: AsyncSession, competitor_id: uuid.UUID) -> Competitor:
    competitor = await db.get(Competitor, competitor_id)
    if not competitor:
        raise NotFoundError("Competitor not found")

    provider = get_youtube_provider()
    channel_data = await provider.get_channel(channel_id=competitor.youtube_channel_id)
    competitor.subscriber_count = channel_data.subscriber_count
    competitor.view_count = channel_data.view_count
    competitor.video_count = channel_data.video_count

    page = await provider.list_channel_videos(competitor.youtube_channel_id)
    for vdata in page.videos:
        video = await db.scalar(
            select(CompetitorVideo).where(CompetitorVideo.youtube_video_id == vdata.youtube_video_id)
        )
        if not video:
            video = CompetitorVideo(
                competitor_id=competitor.id, youtube_video_id=vdata.youtube_video_id
            )
            db.add(video)
        video.title = vdata.title
        video.thumbnail_url = vdata.thumbnail_url
        video.published_at = vdata.published_at
        video.duration_seconds = vdata.duration_seconds
        video.view_count = vdata.view_count
        video.like_count = vdata.like_count
        video.comment_count = vdata.comment_count
        video.category_id = vdata.category_id
        video.tags = ",".join(vdata.tags) if vdata.tags else None

    competitor.last_synced_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(competitor)
    return competitor


async def detect_content_gaps(
    db: AsyncSession, owner_user_id: uuid.UUID, min_competitors: int = 2
) -> list[ContentGap]:
    """Deterministic, explainable gap detection: keywords that recur across
    multiple tracked competitors' titles but that the creator's own channel
    hasn't covered. Returns [] (not fabricated data) when there isn't enough
    tracked competitor history yet."""
    competitors = await db.scalars(
        select(Competitor).where(Competitor.owner_user_id == owner_user_id)
    )
    competitor_ids = [c.id for c in competitors]
    if len(competitor_ids) < min_competitors:
        return []

    comp_videos = await db.scalars(
        select(CompetitorVideo).where(CompetitorVideo.competitor_id.in_(competitor_ids))
    )
    comp_videos = list(comp_videos)
    if not comp_videos:
        return []

    keyword_to_competitors: dict[str, set[uuid.UUID]] = {}
    keyword_to_views: dict[str, int] = Counter()
    for v in comp_videos:
        for kw in extract_keywords(v.title):
            keyword_to_competitors.setdefault(kw, set()).add(v.competitor_id)
            keyword_to_views[kw] += v.view_count or 0

    own_channel_ids = list(
        await db.scalars(select(Channel.id).where(Channel.owner_user_id == owner_user_id))
    )
    own_keywords: set[str] = set()
    if own_channel_ids:
        own_videos = await db.scalars(select(Video).where(Video.channel_id.in_(own_channel_ids)))
        for v in own_videos:
            own_keywords |= extract_keywords(v.title)

    gaps: list[ContentGap] = []
    for kw, comp_set in keyword_to_competitors.items():
        if len(comp_set) < min_competitors:
            continue
        covered = kw in own_keywords
        gaps.append(
            ContentGap(
                keyword=kw,
                competitor_count=len(comp_set),
                total_competitor_views=keyword_to_views[kw],
                creator_has_covered=covered,
                signal=(
                    f"{len(comp_set)} tracked competitors have published videos about "
                    f"'{kw}' totaling {keyword_to_views[kw]:,} views"
                    + ("" if covered else " — you have not covered this topic yet")
                ),
            )
        )

    gaps.sort(key=lambda g: g.total_competitor_views, reverse=True)
    return gaps[:20]
