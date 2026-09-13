"""Competitor onboarding by @handle/URL/search -- a creator must never have
to know or paste a raw UCxxxxxxxx channel id (production audit finding)."""
import uuid

import pytest

from app.core.errors import ValidationError
from app.modules.channels.providers.mock import MockYouTubeProvider
from app.modules.competitors import service as competitors_service
from app.modules.users.models import User, UserRole


async def _make_user(db_session, email: str) -> User:
    user = User(email=email, hashed_password="x", role=UserRole.OWNER)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_resolves_bare_channel_id():
    provider = MockYouTubeProvider()
    result = await competitors_service.resolve_channel_by_identifier(provider, "UC1234567890123456789012")
    assert result.youtube_channel_id == "UC1234567890123456789012"


@pytest.mark.asyncio
async def test_resolves_bare_handle():
    provider = MockYouTubeProvider()
    result = await competitors_service.resolve_channel_by_identifier(provider, "@SomeCreator")
    assert "SomeCreator" in result.title


@pytest.mark.asyncio
async def test_resolves_channel_url():
    provider = MockYouTubeProvider()
    result = await competitors_service.resolve_channel_by_identifier(
        provider, "https://www.youtube.com/channel/UC1234567890123456789012"
    )
    assert result.youtube_channel_id == "UC1234567890123456789012"


@pytest.mark.asyncio
async def test_resolves_handle_url():
    provider = MockYouTubeProvider()
    result = await competitors_service.resolve_channel_by_identifier(
        provider, "https://www.youtube.com/@AnotherCreator"
    )
    assert "AnotherCreator" in result.title


@pytest.mark.asyncio
async def test_resolves_legacy_custom_url():
    provider = MockYouTubeProvider()
    result = await competitors_service.resolve_channel_by_identifier(
        provider, "https://www.youtube.com/c/LegacyName"
    )
    assert "LegacyName" in result.title


@pytest.mark.asyncio
async def test_bare_name_is_rejected_not_guessed():
    """A bare display name is ambiguous -- must never be silently
    auto-resolved to a guessed channel; the caller must use search."""
    provider = MockYouTubeProvider()
    with pytest.raises(ValidationError):
        await competitors_service.resolve_channel_by_identifier(provider, "Some Random Creator Name")


@pytest.mark.asyncio
async def test_search_returns_multiple_candidates_for_selection(monkeypatch):
    monkeypatch.setattr(
        "app.modules.competitors.service.get_youtube_provider", lambda: MockYouTubeProvider()
    )
    results = await competitors_service.search_competitor_candidates("cooking channel")
    assert len(results) >= 2
    assert all("cooking channel" in r.title.lower() for r in results)


@pytest.mark.asyncio
async def test_add_competitor_by_handle(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.modules.competitors.service.get_youtube_provider", lambda: MockYouTubeProvider()
    )
    user = await _make_user(db_session, "byhandle@example.com")
    competitor = await competitors_service.add_competitor(db_session, user.id, "@RivalCreator", None)
    assert competitor.youtube_channel_id == "UC_mock_for_RivalCreator"
    assert "RivalCreator" in competitor.title


@pytest.mark.asyncio
async def test_add_competitor_by_url_and_by_id_collide_as_the_same_channel(db_session, monkeypatch):
    """Adding the same real channel via two different identifier forms
    must be recognized as the same competitor, not tracked twice."""
    monkeypatch.setattr(
        "app.modules.competitors.service.get_youtube_provider", lambda: MockYouTubeProvider()
    )
    user = await _make_user(db_session, "collide@example.com")
    await competitors_service.add_competitor(
        db_session, user.id, "https://www.youtube.com/channel/UC1234567890123456789012", None,
    )
    from app.core.errors import ConflictError

    with pytest.raises(ConflictError):
        await competitors_service.add_competitor(
            db_session, user.id, "UC1234567890123456789012", None,
        )
