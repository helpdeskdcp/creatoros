"""Media download/preview endpoint: ownership-checked, no client-supplied
path involved at all (the id is the only input)."""
import io
import uuid

import pytest

from app.ai.providers.base import AIProviderUnavailableError, RateLimitedError
from app.core.config import get_settings
from app.core.security import create_jwt
from app.modules.media import pexels
from app.modules.users.models import User, UserRole


async def _register(client) -> str:
    email = f"media-{uuid.uuid4().hex[:8]}@example.com"
    resp = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "supersecurepassword1"}
    )
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_download_media_returns_the_real_uploaded_bytes(client):
    token = await _register(client)
    upload = await client.post(
        "/api/v1/media/upload",
        data={"purpose": "THUMBNAIL"},
        files={"file": ("thumb.jpg", io.BytesIO(b"\xff\xd8\xff fake jpeg bytes"), "image/jpeg")},
        headers={"Authorization": f"Bearer {token}"},
    )
    asset_id = upload.json()["id"]

    resp = await client.get(f"/api/v1/media/{asset_id}", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    assert resp.content == b"\xff\xd8\xff fake jpeg bytes"


@pytest.mark.asyncio
async def test_download_media_refuses_another_users_asset(client, db_session):
    token = await _register(client)
    upload = await client.post(
        "/api/v1/media/upload",
        data={"purpose": "THUMBNAIL"},
        files={"file": ("thumb.jpg", io.BytesIO(b"secret bytes"), "image/jpeg")},
        headers={"Authorization": f"Bearer {token}"},
    )
    asset_id = upload.json()["id"]

    attacker = User(email="media-attacker@example.com", hashed_password="x", role=UserRole.OWNER)
    db_session.add(attacker)
    await db_session.commit()
    attacker_token, _ = create_jwt(subject=str(attacker.id), token_type="access")

    resp = await client.get(
        f"/api/v1/media/{asset_id}", headers={"Authorization": f"Bearer {attacker_token}"}
    )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_download_media_returns_404_for_nonexistent_asset(client):
    token = await _register(client)
    resp = await client.get(
        f"/api/v1/media/{uuid.uuid4()}", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Pexels: free stock photo/video search + import as a MediaAsset
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code=200, json_body=None, headers=None):
        self.status_code = status_code
        self._json_body = json_body or {}
        self.headers = headers or {}

    def json(self):
        return self._json_body


class _FakeAsyncClient:
    def __init__(self, response=None):
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None, params=None):
        return self._response


def _settings_with_pexels():
    settings = get_settings()
    settings.pexels_api_key = "test-pexels-key"
    return settings


@pytest.mark.asyncio
async def test_search_photos_normalizes_real_response_shape(monkeypatch):
    monkeypatch.setattr(
        "app.modules.media.pexels.httpx.AsyncClient",
        lambda **kw: _FakeAsyncClient(_FakeResponse(200, {"photos": [{
            "id": 123, "width": 1920, "height": 1080, "photographer": "Jane Doe",
            "photographer_url": "https://pexels.com/@jane", "url": "https://pexels.com/photo/123",
            "src": {"medium": "https://images.pexels.com/123-medium.jpg", "large": "https://images.pexels.com/123-large.jpg"},
        }]})),
    )
    results = await pexels.search_photos(_settings_with_pexels(), "nature")
    assert results == [{
        "id": 123, "width": 1920, "height": 1080, "photographer": "Jane Doe",
        "photographer_url": "https://pexels.com/@jane", "page_url": "https://pexels.com/photo/123",
        "thumbnail_url": "https://images.pexels.com/123-medium.jpg",
        "download_url": "https://images.pexels.com/123-large.jpg",
    }]


@pytest.mark.asyncio
async def test_search_videos_picks_highest_resolution_file(monkeypatch):
    monkeypatch.setattr(
        "app.modules.media.pexels.httpx.AsyncClient",
        lambda **kw: _FakeAsyncClient(_FakeResponse(200, {"videos": [{
            "id": 999, "duration": 20, "width": 1920, "height": 1080, "url": "https://pexels.com/video/999",
            "image": "https://images.pexels.com/999.jpg", "user": {"name": "Studio X"},
            "video_files": [
                {"link": "https://cdn.pexels.com/999-sd.mp4", "width": 640, "height": 360},
                {"link": "https://cdn.pexels.com/999-hd.mp4", "width": 1920, "height": 1080},
            ],
        }]})),
    )
    results = await pexels.search_videos(_settings_with_pexels(), "ocean")
    assert results[0]["download_url"] == "https://cdn.pexels.com/999-hd.mp4"
    assert results[0]["user"] == "Studio X"


@pytest.mark.asyncio
async def test_search_photos_rate_limited_raises_typed_error(monkeypatch):
    monkeypatch.setattr(
        "app.modules.media.pexels.httpx.AsyncClient",
        lambda **kw: _FakeAsyncClient(_FakeResponse(429)),
    )
    with pytest.raises(RateLimitedError):
        await pexels.search_photos(_settings_with_pexels(), "nature")


@pytest.mark.asyncio
async def test_search_photos_missing_key_never_makes_a_request(monkeypatch):
    called = {"value": False}

    def _fail(**kw):
        called["value"] = True
        return _FakeAsyncClient()

    monkeypatch.setattr("app.modules.media.pexels.httpx.AsyncClient", _fail)
    settings = get_settings()
    settings.pexels_api_key = ""
    with pytest.raises(AIProviderUnavailableError):
        await pexels.search_photos(settings, "nature")
    assert called["value"] is False


@pytest.mark.asyncio
async def test_pexels_photo_search_endpoint_returns_normalized_results(client, monkeypatch):
    token = await _register(client)
    get_settings().pexels_api_key = "test-pexels-key"
    monkeypatch.setattr(
        "app.modules.media.pexels.httpx.AsyncClient",
        lambda **kw: _FakeAsyncClient(_FakeResponse(200, {"photos": [{
            "id": 1, "width": 100, "height": 100, "photographer": "P", "photographer_url": "u",
            "url": "pu", "src": {"medium": "m", "large": "l"},
        }]})),
    )
    resp = await client.get(
        "/api/v1/media/pexels/photos", params={"query": "cat"}, headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()[0]["download_url"] == "l"


@pytest.mark.asyncio
async def test_pexels_import_downloads_and_creates_media_asset(client, monkeypatch):
    token = await _register(client)

    async def _fake_download(url, local_path):
        with open(local_path, "wb") as f:
            f.write(b"fake-jpeg-bytes")
        return len(b"fake-jpeg-bytes")

    monkeypatch.setattr("app.modules.media.pexels.download_to_file", _fake_download)

    resp = await client.post(
        "/api/v1/media/pexels/import",
        json={"download_url": "https://images.pexels.com/1-large.jpg", "purpose": "THUMBNAIL", "filename_hint": "cat"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    asset_id = resp.json()["id"]

    download = await client.get(f"/api/v1/media/{asset_id}", headers={"Authorization": f"Bearer {token}"})
    assert download.status_code == 200
    assert download.content == b"fake-jpeg-bytes"
