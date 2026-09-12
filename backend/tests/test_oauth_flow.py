"""End-to-end tests for the GET /channels/oauth/callback flow — the public
landing page Google redirects the user's browser to. This request never
carries an Authorization header (it's a plain top-level navigation from
Google), so these tests deliberately call it with no auth, exactly like a
real browser would."""
import uuid

import pytest
from sqlalchemy import select

from app.modules.channels.models import Channel
from app.modules.channels.service import build_oauth_state


async def _register(client, email: str) -> str:
    resp = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "supersecurepassword1"}
    )
    assert resp.status_code == 201
    return resp.json()["user"]["id"]


@pytest.mark.asyncio
async def test_oauth_callback_get_completes_flow_and_redirects_to_frontend(
    client, db_session, unique_email
):
    user_id = await _register(client, unique_email)
    state = build_oauth_state(uuid.UUID(user_id))

    resp = await client.get(
        "/api/v1/channels/oauth/callback", params={"code": "mock-auth-code", "state": state}
    )

    assert resp.status_code in (302, 303, 307)
    location = resp.headers["location"]
    assert location.startswith("http://localhost:3000/channels?")
    assert "connected=" in location
    assert "oauth_error" not in location

    channel = await db_session.scalar(
        select(Channel).where(Channel.owner_user_id == uuid.UUID(user_id))
    )
    assert channel is not None
    assert channel.oauth_access_token_encrypted is not None


@pytest.mark.asyncio
async def test_oauth_callback_get_rejects_tampered_state(client, unique_email):
    await _register(client, unique_email)

    resp = await client.get(
        "/api/v1/channels/oauth/callback",
        params={"code": "mock-auth-code", "state": "not-a-real-jwt"},
    )

    assert resp.status_code in (302, 303, 307)
    assert "oauth_error=invalid_state" in resp.headers["location"]


@pytest.mark.asyncio
async def test_oauth_callback_get_requires_code_and_state(client):
    resp = await client.get("/api/v1/channels/oauth/callback", params={"state": "whatever"})
    assert resp.status_code in (302, 303, 307)
    assert "oauth_error=missing_code_or_state" in resp.headers["location"]


@pytest.mark.asyncio
async def test_oauth_callback_get_passes_through_google_error(client):
    resp = await client.get(
        "/api/v1/channels/oauth/callback", params={"error": "access_denied"}
    )
    assert resp.status_code in (302, 303, 307)
    assert "oauth_error=access_denied" in resp.headers["location"]


@pytest.mark.asyncio
async def test_oauth_callback_get_never_transfers_ownership_between_users(
    client, db_session, unique_email
):
    owner_id = await _register(client, unique_email)
    owner_state = build_oauth_state(uuid.UUID(owner_id))
    first = await client.get(
        "/api/v1/channels/oauth/callback", params={"code": "code-a", "state": owner_state}
    )
    assert "connected=" in first.headers["location"]

    other_id = await _register(client, f"other-{unique_email}")
    other_state = build_oauth_state(uuid.UUID(other_id))
    second = await client.get(
        "/api/v1/channels/oauth/callback", params={"code": "code-b", "state": other_state}
    )
    assert "oauth_error=connect_failed" in second.headers["location"]

    # The mock provider always resolves to the same channel id regardless of
    # which user authorized it — ownership must still belong to the first user.
    channel = await db_session.scalar(
        select(Channel).where(Channel.owner_user_id == uuid.UUID(owner_id))
    )
    assert channel is not None
    other_owned = await db_session.scalar(
        select(Channel).where(Channel.owner_user_id == uuid.UUID(other_id))
    )
    assert other_owned is None
