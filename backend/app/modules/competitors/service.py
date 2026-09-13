"""Competitor tracking + the Competitor Opportunity Engine. Uses only public
channel/video data reached through the same YouTubeProvider interface as the
creator's own channel — never private competitor analytics."""
import re
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_quality import Metric, insufficient_data, real_metric
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.text import extract_keywords
from app.core.timeutils import ensure_aware
from app.modules.channels.models import Channel
from app.modules.channels.providers import get_youtube_provider
from app.modules.channels.providers.base import ChannelData, YouTubeProvider
from app.modules.competitors.models import Competitor, CompetitorSnapshot, CompetitorVideo
from app.modules.competitors.schemas import ContentGap, FormatBreakdown, GapToTopicResult
from app.modules.videos.models import Video

_CHANNEL_ID_RE = re.compile(r"^UC[\w-]{22}$")
_URL_CHANNEL_ID_RE = re.compile(r"youtube\.com/channel/(UC[\w-]{22})")
_URL_HANDLE_RE = re.compile(r"youtube\.com/@([\w.-]+)")
_URL_LEGACY_RE = re.compile(r"youtube\.com/(?:c|user)/([\w.-]+)")


async def resolve_channel_by_identifier(provider: YouTubeProvider, identifier: str) -> ChannelData:
    """Accepts a raw channel id (UCxxxx...), an @handle, or a full YouTube
    URL (/channel/UCxxx, /@handle, /c/name, /user/name) -- a creator never
    has to know or paste a raw channel id. A bare name that isn't any of
    these is ambiguous and must go through search_competitor_candidates()
    instead of being silently auto-resolved to a guess."""
    identifier = identifier.strip()
    if _CHANNEL_ID_RE.match(identifier):
        return await provider.get_channel(channel_id=identifier)

    m = _URL_CHANNEL_ID_RE.search(identifier)
    if m:
        return await provider.get_channel(channel_id=m.group(1))

    m = _URL_HANDLE_RE.search(identifier) or _URL_LEGACY_RE.search(identifier)
    if m:
        return await provider.get_channel(handle=m.group(1))

    if identifier.startswith("@"):
        return await provider.get_channel(handle=identifier)

    raise ValidationError(
        "Could not resolve this as a channel ID, @handle, or YouTube URL -- "
        "use channel search and select one instead"
    )


async def search_competitor_candidates(query: str, max_results: int = 5) -> list[ChannelData]:
    provider = get_youtube_provider()
    return await provider.search_channels(query, max_results)


async def add_competitor(
    db: AsyncSession, owner_user_id: uuid.UUID, identifier: str, notes: str | None
) -> Competitor:
    """`identifier` is whatever the creator typed -- a channel id, @handle,
    or YouTube URL (see resolve_channel_by_identifier). Resolved to a
    canonical channel BEFORE checking for an existing tracked competitor,
    so two different inputs that mean the same channel correctly collide."""
    provider = get_youtube_provider()
    channel_data = await resolve_channel_by_identifier(provider, identifier)

    existing = await db.scalar(
        select(Competitor).where(
            Competitor.owner_user_id == owner_user_id,
            Competitor.youtube_channel_id == channel_data.youtube_channel_id,
        )
    )
    if existing:
        raise ConflictError("This competitor is already tracked")

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
    db.add(
        CompetitorSnapshot(
            competitor_id=competitor.id, captured_at=competitor.last_synced_at,
            subscriber_count=competitor.subscriber_count, view_count=competitor.view_count,
            video_count=competitor.video_count,
        )
    )
    await db.commit()
    await db.refresh(competitor)
    return competitor


async def compute_competitor_traction(db: AsyncSession, competitor_id: uuid.UUID) -> Metric:
    """Real subscriber/view growth between the two oldest-vs-newest
    snapshots spanning at least 24h -- without CompetitorSnapshot history,
    sync_competitor only ever overwrote current values, making traction
    over time impossible to compute at all (not just imprecise)."""
    snapshots = list(
        await db.scalars(
            select(CompetitorSnapshot)
            .where(CompetitorSnapshot.competitor_id == competitor_id)
            .order_by(CompetitorSnapshot.captured_at)
        )
    )
    if len(snapshots) < 2:
        return insufficient_data(
            len(snapshots),
            "Need at least 2 sync snapshots to compute traction (this fills in automatically "
            "as competitor_sync runs over time)",
        )
    oldest, newest = snapshots[0], snapshots[-1]
    span = ensure_aware(newest.captured_at) - ensure_aware(oldest.captured_at)
    if span < timedelta(hours=24):
        return insufficient_data(
            len(snapshots), "Snapshots span less than 24h -- not enough time to measure real traction yet"
        )
    if oldest.subscriber_count is None or newest.subscriber_count is None:
        return insufficient_data(len(snapshots), "Subscriber count missing on a snapshot")

    subscriber_growth = newest.subscriber_count - oldest.subscriber_count
    days = span.total_seconds() / 86400
    per_week = round(subscriber_growth / days * 7, 1) if days > 0 else 0.0
    return real_metric(per_week, len(snapshots))


async def analyze_competitor_cadence(db: AsyncSession, competitor_id: uuid.UUID) -> Metric:
    """Real upload-frequency-per-week from actual published_at timestamps
    over the last 90 days -- mirrors videos.service._compute_upload_
    frequency's exact discipline for the creator's own channel."""
    videos = list(
        await db.scalars(select(CompetitorVideo).where(CompetitorVideo.competitor_id == competitor_id))
    )
    dated = [v for v in videos if v.published_at is not None]
    if not dated:
        return insufficient_data(0, "No published-date data synced for this competitor yet")

    now = datetime.now(UTC)
    window_start = now - timedelta(days=90)
    recent = [v for v in dated if ensure_aware(v.published_at) >= window_start]
    if len(recent) < 2:
        return insufficient_data(len(recent), "Fewer than 2 videos published in the last 90 days")

    per_week = round(len(recent) / (90 / 7), 2)
    return real_metric(per_week, len(recent))


async def analyze_competitor_formats(db: AsyncSession, competitor_id: uuid.UUID) -> FormatBreakdown:
    """Real Shorts-vs-long-form split by duration (<=60s = Short, matching
    YouTube's own definition and how videos.models.VideoFormat classifies
    the creator's own content) -- CompetitorVideo has no format column of
    its own, so this classifies from duration_seconds directly."""
    videos = list(
        await db.scalars(
            select(CompetitorVideo).where(
                CompetitorVideo.competitor_id == competitor_id,
                CompetitorVideo.duration_seconds.is_not(None),
            )
        )
    )
    if not videos:
        return FormatBreakdown(shorts_count=0, long_form_count=0, quality="INSUFFICIENT_DATA")

    shorts = sum(1 for v in videos if v.duration_seconds <= 60)
    long_form = len(videos) - shorts
    return FormatBreakdown(shorts_count=shorts, long_form_count=long_form, quality="REAL")


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
        for own_video in own_videos:
            own_keywords |= extract_keywords(own_video.title)

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


async def create_topics_from_content_gaps(
    db: AsyncSession, owner_user_id: uuid.UUID, top_n: int = 5
) -> list[GapToTopicResult]:
    """Connects gap detection to the EXISTING topic/opportunity/
    recommendation pipeline instead of leaving it an isolated report --
    reuses trends.service's own keyword-level Trend rows (refresh_trends
    already computes real content_gap/momentum/competition scores per
    keyword) rather than building a second, parallel scoring system.

    A gap keyword with no matching Trend yet (refresh_trends hasn't run,
    or that keyword didn't clear MIN_SAMPLE_SIZE_TREND) still gets a
    Topic created -- but honestly: compute_opportunity will correctly
    return INSUFFICIENT_DATA for it rather than this function inventing
    a score.
    """
    from app.modules.topics.models import Topic
    from app.modules.trends.models import Trend

    gaps = await detect_content_gaps(db, owner_user_id)
    uncovered = [g for g in gaps if not g.creator_has_covered][:top_n]

    results: list[GapToTopicResult] = []
    for gap in uncovered:
        existing_topic = await db.scalar(
            select(Topic).where(Topic.owner_user_id == owner_user_id, Topic.title == gap.keyword)
        )
        if existing_topic:
            results.append(
                GapToTopicResult(keyword=gap.keyword, topic_id=existing_topic.id, created=False,
                                  reason="Topic already exists for this keyword")
            )
            continue

        trend = await db.scalar(
            select(Trend).where(Trend.owner_user_id == owner_user_id, Trend.keyword == gap.keyword)
        )
        topic = Topic(
            owner_user_id=owner_user_id,
            title=gap.keyword,
            description=gap.signal,
            trend_id=trend.id if trend else None,
        )
        db.add(topic)
        await db.flush()
        results.append(
            GapToTopicResult(
                keyword=gap.keyword, topic_id=topic.id, created=True,
                reason=None if trend else "No matching Trend yet -- opportunity score will read INSUFFICIENT_DATA until refresh_trends detects this keyword",
            )
        )

    await db.commit()
    return results
