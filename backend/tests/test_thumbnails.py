"""Thumbnail brief image attachment: ownership-checked, stores a direct
image URL (e.g. from the Pexels picker) without re-downloading it."""
import uuid

import pytest

from app.modules.thumbnails.models import ThumbnailBrief


async def _register(client) -> tuple[str, uuid.UUID]:
    email = f"thumb-{uuid.uuid4().hex[:8]}@example.com"
    resp = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "supersecurepassword1"}
    )
    return resp.json()["access_token"], uuid.UUID(resp.json()["user"]["id"])


def _brief(owner_user_id: uuid.UUID) -> ThumbnailBrief:
    return ThumbnailBrief(
        owner_user_id=owner_user_id, subject="a cat", emotion="curious", text_overlay="WOW",
        text_overlay_length=3, version=1,
    )


@pytest.mark.asyncio
async def test_attach_image_sets_image_path_and_provider(client, db_session):
    token, owner_id = await _register(client)
    brief = _brief(owner_id)
    db_session.add(brief)
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/thumbnails/{brief.id}/image",
        json={"image_url": "https://images.pexels.com/photos/1/cat-large.jpg", "image_provider": "pexels"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["image_path"] == "https://images.pexels.com/photos/1/cat-large.jpg"
    assert body["image_provider"] == "pexels"


@pytest.mark.asyncio
async def test_attach_image_refuses_another_users_brief(client, db_session):
    _, owner_id = await _register(client)
    attacker_token, _ = await _register(client)
    brief = _brief(owner_id)
    db_session.add(brief)
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/thumbnails/{brief.id}/image",
        json={"image_url": "https://images.pexels.com/photos/1/cat-large.jpg"},
        headers={"Authorization": f"Bearer {attacker_token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_attach_image_returns_404_for_nonexistent_brief(client):
    token, _ = await _register(client)
    resp = await client.post(
        f"/api/v1/thumbnails/{uuid.uuid4()}/image",
        json={"image_url": "https://images.pexels.com/photos/1/cat-large.jpg"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
