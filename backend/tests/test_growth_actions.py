"""Daily Growth Missions: GrowthAction rows and the run_daily_growth_agent
Celery task were real (backend/app/modules/analytics/models.py,
app/jobs/tasks.py) but the production audit found no API endpoint ever
exposed them, and the dashboard had no widget for them at all -- 'Today's
AI Growth Missions' existed only as unused backend scaffolding."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.analytics import service as analytics_service
from app.modules.analytics.models import GrowthAction


async def _register(client, email: str) -> tuple[str, str]:
    resp = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "supersecurepassword1"}
    )
    return resp.json()["access_token"], resp.json()["user"]["id"]


@pytest.mark.asyncio
async def test_growth_actions_endpoint_returns_only_latest_run(client, db_session, unique_email):
    token, user_id = await _register(client, unique_email)
    headers = {"Authorization": f"Bearer {token}"}

    older = datetime.now(UTC) - timedelta(days=1)
    newer = datetime.now(UTC)
    db_session.add_all(
        [
            GrowthAction(
                owner_user_id=uuid.UUID(user_id), run_date=older, priority=1, action_type="OLD",
                title="Old mission", reason="stale", confidence="LOW", execution_status="pending",
            ),
            GrowthAction(
                owner_user_id=uuid.UUID(user_id), run_date=newer, priority=2, action_type="NEW_B",
                title="New mission B", reason="fresh", confidence="MEDIUM", execution_status="pending",
            ),
            GrowthAction(
                owner_user_id=uuid.UUID(user_id), run_date=newer, priority=1, action_type="NEW_A",
                title="New mission A", reason="fresh", confidence="HIGH", execution_status="pending",
            ),
        ]
    )
    await db_session.commit()

    resp = await client.get("/api/v1/analytics/growth-actions", headers=headers)

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2  # only the latest run_date's actions
    assert [a["title"] for a in body] == ["New mission A", "New mission B"]  # ordered by priority


@pytest.mark.asyncio
async def test_growth_actions_empty_when_agent_never_ran(client, db_session, unique_email):
    token, _ = await _register(client, unique_email)
    resp = await client.get(
        "/api/v1/analytics/growth-actions", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_growth_actions_scoped_to_owning_user_only(client, db_session, unique_email):
    token, user_id = await _register(client, unique_email)
    other_id = uuid.uuid4()
    db_session.add(
        GrowthAction(
            owner_user_id=other_id, run_date=datetime.now(UTC), priority=1, action_type="X",
            title="Not yours", reason="r", confidence="LOW", execution_status="pending",
        )
    )
    await db_session.commit()

    resp = await client.get(
        "/api/v1/analytics/growth-actions", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.json() == []
