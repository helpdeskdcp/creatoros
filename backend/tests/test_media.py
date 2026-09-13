"""Media download/preview endpoint: ownership-checked, no client-supplied
path involved at all (the id is the only input)."""
import io
import uuid

import pytest

from app.core.security import create_jwt
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
