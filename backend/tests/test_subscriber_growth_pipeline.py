"""The production audit found compute_subscriber_growth()'s formula was
real but permanently orphaned: nothing ever called
YouTubeDataAPIProvider.get_channel_analytics(), so every subscriber-growth
metric was stuck at INSUFFICIENT_DATA regardless of how much a channel
synced. This proves the fixed pipeline actually populates real data for
an OAuth-connected channel."""
import uuid

import pytest

from app.core.data_quality import DataQuality
from app.modules.analytics import service as analytics_service
from app.modules.channels.service import build_oauth_state


async def _register_and_connect(client) -> tuple[str, str]:
    email = f"subgrowth-{uuid.uuid4().hex[:8]}@example.com"
    register = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "supersecurepassword1"}
    )
    token = register.json()["access_token"]
    user_id = register.json()["user"]["id"]

    state = build_oauth_state(uuid.UUID(user_id))
    callback = await client.get(
        "/api/v1/channels/oauth/callback", params={"code": "mock-auth-code", "state": state}
    )
    location = callback.headers["location"]
    assert "connected=" in location
    channel_id = location.split("connected=")[1].split("&")[0]
    return token, channel_id


@pytest.mark.asyncio
async def test_oauth_sync_populates_subscriber_growth_data(client, db_session):
    token, channel_id = await _register_and_connect(client)
    headers = {"Authorization": f"Bearer {token}"}

    sync = await client.post(f"/api/v1/channels/{channel_id}/sync", headers=headers)
    assert sync.status_code == 200
    assert sync.json()["sync_status"] == "SUCCEEDED"

    from app.modules.channels.models import Channel

    channel = await db_session.get(Channel, uuid.UUID(channel_id))
    growth = await analytics_service.compute_subscriber_growth(db_session, channel)

    # Real data from the mock provider's get_channel_analytics -- no
    # longer permanently stuck at INSUFFICIENT_DATA now that the sync
    # pipeline actually calls it for OAuth-connected channels.
    assert growth.subscriber_growth_rate.quality == DataQuality.REAL
    assert growth.subscriber_growth_rate.value == sum(2 * i for i in range(1, 11))  # mock provider's fixture
    assert growth.subscriber_conversion_rate.quality == DataQuality.REAL
    assert growth.subscriber_conversion_rate.value > 0


@pytest.mark.asyncio
async def test_growth_scorecard_subscriber_conversion_score_is_real_after_oauth_sync(client, db_session):
    token, channel_id = await _register_and_connect(client)
    headers = {"Authorization": f"Bearer {token}"}
    await client.post(f"/api/v1/channels/{channel_id}/sync", headers=headers)

    from app.modules.channels.models import Channel

    channel = await db_session.get(Channel, uuid.UUID(channel_id))
    scorecard = await analytics_service.compute_growth_scorecard(db_session, channel)

    assert scorecard.subscriber_conversion_score.quality == DataQuality.REAL
    assert 0 <= scorecard.subscriber_conversion_score.value <= 100


@pytest.mark.asyncio
async def test_public_connect_sync_never_populates_subscriber_growth(client, db_session):
    """A channel connected WITHOUT OAuth (public-only) has no access
    token -- must never attempt (or fake) the Analytics call."""
    email = f"public-{uuid.uuid4().hex[:8]}@example.com"
    register = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "supersecurepassword1"}
    )
    token = register.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    connect = await client.post(
        "/api/v1/channels", json={"youtube_channel_id": "UC_public_only"}, headers=headers
    )
    channel_id = connect.json()["id"]
    sync = await client.post(f"/api/v1/channels/{channel_id}/sync", headers=headers)
    assert sync.status_code == 200

    from app.modules.channels.models import Channel

    channel = await db_session.get(Channel, uuid.UUID(channel_id))
    growth = await analytics_service.compute_subscriber_growth(db_session, channel)

    assert growth.subscriber_growth_rate.quality == DataQuality.INSUFFICIENT_DATA
