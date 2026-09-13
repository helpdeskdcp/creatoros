"""Competitor intelligence: real historical traction (was previously
impossible -- sync only ever overwrote current values), real cadence/
format analysis from actual synced video data, and gap detection
actually connected to the existing topic/opportunity pipeline instead of
being an isolated report."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.data_quality import DataQuality
from app.modules.competitors import service as competitors_service
from app.modules.competitors.models import Competitor, CompetitorSnapshot, CompetitorVideo
from app.modules.topics.models import Topic
from app.modules.trends.models import Trend, TrendSource
from app.modules.users.models import User, UserRole


async def _make_user(db_session, email: str) -> User:
    user = User(email=email, hashed_password="x", role=UserRole.OWNER)
    db_session.add(user)
    await db_session.flush()
    return user


async def _make_competitor(db_session, owner_id) -> Competitor:
    competitor = Competitor(
        owner_user_id=owner_id, youtube_channel_id=f"UC_{uuid.uuid4().hex[:8]}", title="Rival Channel",
    )
    db_session.add(competitor)
    await db_session.commit()
    await db_session.refresh(competitor)
    return competitor


@pytest.mark.asyncio
async def test_traction_insufficient_with_fewer_than_two_snapshots(db_session):
    user = await _make_user(db_session, "trac1@example.com")
    competitor = await _make_competitor(db_session, user.id)

    result = await competitors_service.compute_competitor_traction(db_session, competitor.id)

    assert result.quality == DataQuality.INSUFFICIENT_DATA
    assert result.value is None


@pytest.mark.asyncio
async def test_traction_insufficient_when_snapshots_too_close_together(db_session):
    user = await _make_user(db_session, "trac2@example.com")
    competitor = await _make_competitor(db_session, user.id)
    now = datetime.now(UTC)
    db_session.add(CompetitorSnapshot(competitor_id=competitor.id, captured_at=now - timedelta(hours=1), subscriber_count=1000))
    db_session.add(CompetitorSnapshot(competitor_id=competitor.id, captured_at=now, subscriber_count=1010))
    await db_session.commit()

    result = await competitors_service.compute_competitor_traction(db_session, competitor.id)

    assert result.quality == DataQuality.INSUFFICIENT_DATA


@pytest.mark.asyncio
async def test_traction_computes_real_weekly_growth_rate(db_session):
    user = await _make_user(db_session, "trac3@example.com")
    competitor = await _make_competitor(db_session, user.id)
    now = datetime.now(UTC)
    # +700 subscribers over exactly 7 days -> 700/week
    db_session.add(CompetitorSnapshot(competitor_id=competitor.id, captured_at=now - timedelta(days=7), subscriber_count=10000))
    db_session.add(CompetitorSnapshot(competitor_id=competitor.id, captured_at=now, subscriber_count=10700))
    await db_session.commit()

    result = await competitors_service.compute_competitor_traction(db_session, competitor.id)

    assert result.quality == DataQuality.REAL
    assert abs(result.value - 700.0) < 1.0


@pytest.mark.asyncio
async def test_cadence_insufficient_with_no_recent_videos(db_session):
    user = await _make_user(db_session, "cad1@example.com")
    competitor = await _make_competitor(db_session, user.id)

    result = await competitors_service.analyze_competitor_cadence(db_session, competitor.id)

    assert result.quality == DataQuality.INSUFFICIENT_DATA


@pytest.mark.asyncio
async def test_cadence_computes_real_uploads_per_week(db_session):
    user = await _make_user(db_session, "cad2@example.com")
    competitor = await _make_competitor(db_session, user.id)
    now = datetime.now(UTC)
    for i in range(9):  # 9 videos over the last 63 days -> ~1/week
        db_session.add(
            CompetitorVideo(
                competitor_id=competitor.id, youtube_video_id=f"v{i}", title=f"Video {i}",
                published_at=now - timedelta(days=i * 7),
            )
        )
    await db_session.commit()

    result = await competitors_service.analyze_competitor_cadence(db_session, competitor.id)

    assert result.quality == DataQuality.REAL
    assert 0.5 < result.value < 1.5


@pytest.mark.asyncio
async def test_format_breakdown_classifies_by_real_duration(db_session):
    user = await _make_user(db_session, "fmt1@example.com")
    competitor = await _make_competitor(db_session, user.id)
    db_session.add(CompetitorVideo(competitor_id=competitor.id, youtube_video_id="s1", title="Short", duration_seconds=45))
    db_session.add(CompetitorVideo(competitor_id=competitor.id, youtube_video_id="s2", title="Short2", duration_seconds=30))
    db_session.add(CompetitorVideo(competitor_id=competitor.id, youtube_video_id="l1", title="Long", duration_seconds=600))
    await db_session.commit()

    result = await competitors_service.analyze_competitor_formats(db_session, competitor.id)

    assert result.quality == "REAL"
    assert result.shorts_count == 2
    assert result.long_form_count == 1


@pytest.mark.asyncio
async def test_format_breakdown_insufficient_with_no_duration_data(db_session):
    user = await _make_user(db_session, "fmt2@example.com")
    competitor = await _make_competitor(db_session, user.id)

    result = await competitors_service.analyze_competitor_formats(db_session, competitor.id)

    assert result.quality == "INSUFFICIENT_DATA"


@pytest.mark.asyncio
async def test_sync_competitor_writes_a_real_snapshot(db_session):
    user = await _make_user(db_session, "sync1@example.com")
    competitor = await _make_competitor(db_session, user.id)
    await db_session.commit()

    await competitors_service.sync_competitor(db_session, competitor.id)

    from sqlalchemy import select

    snapshots = list(
        await db_session.scalars(select(CompetitorSnapshot).where(CompetitorSnapshot.competitor_id == competitor.id))
    )
    assert len(snapshots) == 1
    assert snapshots[0].subscriber_count is not None


@pytest.mark.asyncio
async def test_create_topics_from_gaps_links_matching_trend(db_session):
    """The core 'connect gaps to topic generation' requirement: a gap
    keyword with a matching real Trend becomes a real, opportunity-
    scoreable Topic -- not just a read-only report line."""
    user = await _make_user(db_session, "gap1@example.com")
    competitor_a = await _make_competitor(db_session, user.id)
    competitor_b = await _make_competitor(db_session, user.id)
    for i, comp in enumerate([competitor_a, competitor_b]):
        db_session.add(
            CompetitorVideo(
                competitor_id=comp.id, youtube_video_id=f"gapvid{i}",
                title="Amazing lighting setup tutorial", view_count=50000,
            )
        )
    db_session.add(
        Trend(
            owner_user_id=user.id, keyword="lighting", source=TrendSource.COMPETITOR_MOMENTUM,
            trend_score=80, growth_score=80, competition_score=20, audience_fit_score=80,
            creator_fit_score=50, timeliness_score=100, content_gap_score=100,
            opportunity_score=80, sample_size=10, explanation="test trend", detected_at=datetime.now(UTC),
        )
    )
    await db_session.commit()

    results = await competitors_service.create_topics_from_content_gaps(db_session, user.id)

    matching = [r for r in results if r.keyword == "lighting"]
    assert len(matching) == 1
    assert matching[0].created is True
    assert matching[0].topic_id is not None
    assert matching[0].reason is None  # a trend was found -- no caveat needed

    topic = await db_session.get(Topic, matching[0].topic_id)
    assert topic.trend_id is not None


@pytest.mark.asyncio
async def test_create_topics_from_gaps_is_honest_without_a_matching_trend(db_session):
    user = await _make_user(db_session, "gap2@example.com")
    competitor_a = await _make_competitor(db_session, user.id)
    competitor_b = await _make_competitor(db_session, user.id)
    for i, comp in enumerate([competitor_a, competitor_b]):
        db_session.add(
            CompetitorVideo(
                competitor_id=comp.id, youtube_video_id=f"gapvid2{i}",
                title="Unusual camera technique explained", view_count=30000,
            )
        )
    await db_session.commit()

    results = await competitors_service.create_topics_from_content_gaps(db_session, user.id)

    assert len(results) >= 1
    for r in results:
        assert r.created is True
        assert r.reason is not None
        assert "INSUFFICIENT_DATA" in r.reason
        topic = await db_session.get(Topic, r.topic_id)
        assert topic.trend_id is None  # honestly unlinked, not guessed


@pytest.mark.asyncio
async def test_create_topics_from_gaps_never_duplicates_an_existing_topic(db_session):
    user = await _make_user(db_session, "gap3@example.com")
    competitor_a = await _make_competitor(db_session, user.id)
    competitor_b = await _make_competitor(db_session, user.id)
    for i, comp in enumerate([competitor_a, competitor_b]):
        db_session.add(
            CompetitorVideo(
                competitor_id=comp.id, youtube_video_id=f"gapvid3{i}",
                title="Repeated keyword topic here", view_count=1000,
            )
        )
    await db_session.commit()

    first_run = await competitors_service.create_topics_from_content_gaps(db_session, user.id)
    second_run = await competitors_service.create_topics_from_content_gaps(db_session, user.id)

    first_ids = {r.topic_id for r in first_run if r.created}
    for r in second_run:
        if r.topic_id in first_ids:
            assert r.created is False
            assert "already exists" in r.reason
