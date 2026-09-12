import pytest


async def _register_and_token(client, email: str) -> str:
    resp = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "supersecurepassword1"}
    )
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_connect_and_sync_channel_uses_mock_provider(client, unique_email):
    token = await _register_and_token(client, unique_email)
    headers = {"Authorization": f"Bearer {token}"}

    connect = await client.post(
        "/api/v1/channels", json={"youtube_channel_id": "UC_test_channel"}, headers=headers
    )
    assert connect.status_code == 201
    channel = connect.json()
    assert channel["title"] == "Demo Creator Channel"
    assert channel["sync_status"] == "NEVER_SYNCED"

    sync = await client.post(f"/api/v1/channels/{channel['id']}/sync", headers=headers)
    assert sync.status_code == 200
    assert sync.json()["sync_status"] == "SUCCEEDED"

    videos = await client.get(f"/api/v1/videos/channel/{channel['id']}", headers=headers)
    assert videos.status_code == 200
    assert len(videos.json()) == 10


@pytest.mark.asyncio
async def test_channel_intelligence_never_fabricates_velocity(client, unique_email):
    token = await _register_and_token(client, unique_email)
    headers = {"Authorization": f"Bearer {token}"}

    connect = await client.post(
        "/api/v1/channels", json={"youtube_channel_id": "UC_test_channel_2"}, headers=headers
    )
    channel_id = connect.json()["id"]
    await client.post(f"/api/v1/channels/{channel_id}/sync", headers=headers)

    resp = await client.get(f"/api/v1/videos/channel/{channel_id}/intelligence", headers=headers)
    assert resp.status_code == 200
    intel = resp.json()

    # Only one snapshot per video exists after a single sync — velocity
    # requires two snapshots spanning 7+ days, so it MUST be INSUFFICIENT_DATA
    # rather than a fabricated number.
    assert intel["views_velocity_7d"]["quality"] == "INSUFFICIENT_DATA"
    assert intel["views_velocity_7d"]["value"] is None

    # But average/median views over 10 real synced videos should compute.
    assert intel["average_views"]["quality"] == "REAL"
    assert intel["average_views"]["value"] is not None
    assert len(intel["top_videos"]) == 5


@pytest.mark.asyncio
async def test_channel_not_owned_by_user_returns_404(client, unique_email):
    token = await _register_and_token(client, unique_email)
    other_token = await _register_and_token(client, f"other-{unique_email}")

    connect = await client.post(
        "/api/v1/channels",
        json={"youtube_channel_id": "UC_owned_by_first"},
        headers={"Authorization": f"Bearer {token}"},
    )
    channel_id = connect.json()["id"]

    resp = await client.get(
        f"/api/v1/channels/{channel_id}", headers={"Authorization": f"Bearer {other_token}"}
    )
    assert resp.status_code == 404
