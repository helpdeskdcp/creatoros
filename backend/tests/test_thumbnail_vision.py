"""Thumbnail Vision Analysis: deterministic pixel metrics computed from a
real (or, in tests, synthesized) image -- never an AI-generated guess.
Test images are synthesized in-memory with Pillow, matching this
codebase's established convention (ffmpeg tests synthesize video via
lavfi) of never using real network/binary assets in the test suite."""
import io
import uuid

import pytest
from PIL import Image

from app.core.errors import ValidationError, NotFoundError
from app.modules.channels.models import Channel
from app.modules.thumbnail_vision import analysis
from app.modules.thumbnail_vision import service as tv_service
from app.modules.users.models import User, UserRole
from app.modules.videos.models import Video


def _make_image_bytes(size=(1280, 720), color=(128, 128, 128), pattern=None) -> bytes:
    img = Image.new("RGB", size, color)
    if pattern == "checkerboard":
        pixels = img.load()
        block = 20
        for x in range(size[0]):
            for y in range(size[1]):
                if (x // block + y // block) % 2 == 0:
                    pixels[x, y] = (0, 0, 0)
                else:
                    pixels[x, y] = (255, 255, 255)
    elif pattern == "vibrant":
        pixels = img.load()
        for x in range(size[0]):
            for y in range(size[1]):
                pixels[x, y] = ((x * 7) % 256, (y * 13) % 256, ((x + y) * 3) % 256)
    elif pattern == "centered_subject":
        pixels = img.load()
        cx0, cy0 = size[0] // 4, size[1] // 4
        cx1, cy1 = 3 * size[0] // 4, 3 * size[1] // 4
        for x in range(cx0, cx1):
            for y in range(cy0, cy1):
                pixels[x, y] = (0, 0, 0) if (x + y) % 2 == 0 else (255, 255, 255)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Pure analysis functions -- no DB, no network
# ---------------------------------------------------------------------------

def test_flat_gray_image_has_low_contrast_and_colorfulness():
    metrics = analysis.analyze_thumbnail(_make_image_bytes(color=(128, 128, 128)))
    assert metrics.contrast_score < 5
    assert metrics.colorfulness_score < 5


def test_checkerboard_has_high_contrast():
    metrics = analysis.analyze_thumbnail(_make_image_bytes(pattern="checkerboard"))
    assert metrics.contrast_score > 90


def test_vibrant_pattern_has_high_colorfulness():
    metrics = analysis.analyze_thumbnail(_make_image_bytes(pattern="vibrant"))
    assert metrics.colorfulness_score > 15


def test_correct_resolution_and_aspect_ratio_pass():
    metrics = analysis.analyze_thumbnail(_make_image_bytes(size=(1280, 720)))
    assert metrics.meets_min_resolution is True
    assert metrics.meets_aspect_ratio is True


def test_undersized_resolution_fails_the_check():
    metrics = analysis.analyze_thumbnail(_make_image_bytes(size=(320, 180)))
    assert metrics.meets_min_resolution is False
    assert metrics.meets_aspect_ratio is True  # still 16:9, just too small


def test_wrong_aspect_ratio_fails_the_check():
    metrics = analysis.analyze_thumbnail(_make_image_bytes(size=(1280, 1280)))  # square
    assert metrics.meets_aspect_ratio is False


def test_centered_subject_scores_higher_prominence_than_flat_image():
    flat = analysis.analyze_thumbnail(_make_image_bytes(color=(128, 128, 128)))
    centered = analysis.analyze_thumbnail(_make_image_bytes(pattern="centered_subject"))
    assert centered.subject_prominence_score > flat.subject_prominence_score


def test_recommendations_cite_real_measured_numbers():
    metrics = analysis.analyze_thumbnail(_make_image_bytes(size=(320, 180), color=(30, 30, 30)))
    recs = analysis.generate_recommendations(metrics)
    assert any("320x180" in r for r in recs)
    assert any(str(metrics.brightness_score) in r for r in recs)


def test_good_thumbnail_produces_no_recommendations():
    metrics = analysis.analyze_thumbnail(_make_image_bytes(pattern="vibrant", size=(1280, 720)))
    # Force acceptable values directly to test the "no complaints" path
    # independent of exactly how vibrant/checkerboard synthetic patterns score.
    metrics.meets_min_resolution = True
    metrics.meets_aspect_ratio = True
    metrics.contrast_score = 50.0
    metrics.brightness_score = 50.0
    metrics.colorfulness_score = 40.0
    metrics.subject_prominence_score = 120.0
    assert analysis.generate_recommendations(metrics) == []


# ---------------------------------------------------------------------------
# Service layer -- DB + a stubbed HTTP fetch of the "real" thumbnail
# ---------------------------------------------------------------------------

async def _make_user_channel_video(db_session, email: str, thumbnail_url: str | None = "https://example.com/thumb.jpg") -> tuple[User, Video]:
    user = User(email=email, hashed_password="x", role=UserRole.OWNER)
    db_session.add(user)
    await db_session.flush()
    channel = Channel(owner_user_id=user.id, youtube_channel_id=f"UC_{uuid.uuid4().hex[:10]}", title="Test Channel")
    db_session.add(channel)
    await db_session.flush()
    video = Video(
        channel_id=channel.id, youtube_video_id=f"vid_{uuid.uuid4().hex[:8]}", title="T",
        thumbnail_url=thumbnail_url,
    )
    db_session.add(video)
    await db_session.commit()
    await db_session.refresh(user)
    await db_session.refresh(video)
    return user, video


class _FakeResponse:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code


class _FakeAsyncClient:
    def __init__(self, content: bytes, status_code: int = 200):
        self._content = content
        self._status_code = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        return _FakeResponse(self._content, self._status_code)


@pytest.mark.asyncio
async def test_analyze_video_thumbnail_persists_real_metrics(db_session, monkeypatch):
    user, video = await _make_user_channel_video(db_session, "thumb@example.com")
    image_bytes = _make_image_bytes(pattern="checkerboard")
    monkeypatch.setattr(
        "app.modules.thumbnail_vision.service.httpx.AsyncClient",
        lambda **kwargs: _FakeAsyncClient(image_bytes),
    )

    analysis_result = await tv_service.analyze_video_thumbnail(db_session, video.id, user.id)
    assert analysis_result.contrast_score > 90
    assert analysis_result.width == 1280
    assert analysis_result.height == 720

    history = await tv_service.list_analyses_for_video(db_session, video.id, user.id)
    assert len(history) == 1


@pytest.mark.asyncio
async def test_analyze_fails_cleanly_without_a_synced_thumbnail(db_session):
    user, video = await _make_user_channel_video(db_session, "nothumb@example.com", thumbnail_url=None)
    with pytest.raises(ValidationError):
        await tv_service.analyze_video_thumbnail(db_session, video.id, user.id)


@pytest.mark.asyncio
async def test_analyze_fails_cleanly_on_http_error(db_session, monkeypatch):
    user, video = await _make_user_channel_video(db_session, "httperr@example.com")
    monkeypatch.setattr(
        "app.modules.thumbnail_vision.service.httpx.AsyncClient",
        lambda **kwargs: _FakeAsyncClient(b"", status_code=404),
    )
    with pytest.raises(ValidationError):
        await tv_service.analyze_video_thumbnail(db_session, video.id, user.id)


@pytest.mark.asyncio
async def test_creator_isolation_cannot_analyze_another_users_video(db_session):
    _owner, video = await _make_user_channel_video(db_session, "isoowner@example.com")
    attacker = User(email="isoattacker@example.com", hashed_password="x", role=UserRole.OWNER)
    db_session.add(attacker)
    await db_session.commit()
    await db_session.refresh(attacker)

    with pytest.raises(NotFoundError):
        await tv_service.analyze_video_thumbnail(db_session, video.id, attacker.id)
