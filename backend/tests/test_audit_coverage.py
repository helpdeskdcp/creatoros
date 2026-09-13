"""The production audit found audit logging wired into publishing only --
OAuth connects, AI generation, and kill-switch toggles were all silently
unaudited despite the in-app claim 'every autonomous action is recorded'.
These tests prove each of those now writes a real audit_logs row."""
import json

import pytest
from sqlalchemy import select

from app.ai.dependency import get_orchestrator
from app.ai.orchestrator import AIOrchestrator
from app.ai.providers.base import AICompletionResult, AIProvider
from app.main import app
from app.modules.audit.models import AuditLog


class _ScriptedHookProvider(AIProvider):
    """A fast, deterministic stand-in for the real LLM provider -- no test
    should depend on network access or a real AI backend being reachable."""

    name = "scripted-test-provider"

    async def is_available(self) -> bool:
        return True

    async def complete(self, messages, *, temperature=0.4, max_tokens=2000, json_mode=False):
        body = json.dumps(
            {
                "hooks": [
                    {
                        "text": "Here's the fastest way to edit your videos.",
                        "category": "curiosity",
                        "clarity_score": 80,
                        "curiosity_score": 85,
                        "specificity_score": 70,
                        "audience_fit_score": 75,
                    },
                    {
                        "text": "Stop wasting hours editing -- do this instead.",
                        "category": "problem",
                        "clarity_score": 82,
                        "curiosity_score": 88,
                        "specificity_score": 72,
                        "audience_fit_score": 79,
                    },
                ]
            }
        )
        return AICompletionResult(
            text=body, provider=self.name, model="scripted-1", prompt_tokens=10, completion_tokens=20
        )


@pytest.fixture(autouse=True)
def _fake_ai_orchestrator():
    app.dependency_overrides[get_orchestrator] = lambda: AIOrchestrator(primary=_ScriptedHookProvider())
    yield
    app.dependency_overrides.pop(get_orchestrator, None)


async def _register_and_token(client, email: str) -> str:
    resp = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "supersecurepassword1"}
    )
    return resp.json()["access_token"]


@pytest.mark.asyncio
async def test_ai_generation_success_is_audited(client, db_session, unique_email):
    token = await _register_and_token(client, unique_email)
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post(
        "/api/v1/hooks/generate",
        json={"topic": "how to edit faster", "count": 2},
        headers=headers,
    )
    assert resp.status_code == 200

    logs = list(
        await db_session.scalars(select(AuditLog).where(AuditLog.action_type == "ai_generate:generate_hooks"))
    )
    assert len(logs) == 1
    assert logs[0].result == "success"
    assert logs[0].provider  # model name, never empty


@pytest.mark.asyncio
async def test_ai_generation_cache_hit_is_also_audited(client, db_session, unique_email):
    token = await _register_and_token(client, unique_email)
    headers = {"Authorization": f"Bearer {token}"}

    payload = {"topic": "same topic twice", "count": 2}
    first = await client.post("/api/v1/hooks/generate", json=payload, headers=headers)
    second = await client.post("/api/v1/hooks/generate", json=payload, headers=headers)
    assert first.status_code == 200
    assert second.status_code == 200

    logs = list(
        await db_session.scalars(select(AuditLog).where(AuditLog.action_type == "ai_generate:generate_hooks"))
    )
    # One real generation + one cache hit -- both audited, not just the first.
    assert len(logs) == 2
    assert {log.authorization_state for log in logs} == {"generated", "cache_hit"}


@pytest.mark.asyncio
async def test_oauth_connect_success_is_audited(client, db_session, unique_email):
    from app.modules.channels.service import build_oauth_state

    token = await _register_and_token(client, unique_email)
    user_id = (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})).json()["id"]
    state = build_oauth_state(__import__("uuid").UUID(user_id))

    resp = await client.get("/api/v1/channels/oauth/callback", params={"code": "mock-code", "state": state})
    assert "connected=" in resp.headers["location"]

    logs = list(await db_session.scalars(select(AuditLog).where(AuditLog.action_type == "oauth_connect")))
    assert len(logs) == 1
    assert logs[0].result == "success"
    assert logs[0].provider == "youtube"


@pytest.mark.asyncio
async def test_oauth_connect_cross_user_conflict_is_audited_as_blocked(client, db_session, unique_email):
    import uuid as uuid_mod

    from app.modules.channels.service import build_oauth_state

    owner_token = await _register_and_token(client, unique_email)
    owner_id = (
        await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {owner_token}"})
    ).json()["id"]
    owner_state = build_oauth_state(uuid_mod.UUID(owner_id))
    first = await client.get("/api/v1/channels/oauth/callback", params={"code": "code-a", "state": owner_state})
    assert "connected=" in first.headers["location"]

    other_token = await _register_and_token(client, f"other-{unique_email}")
    other_id = (
        await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {other_token}"})
    ).json()["id"]
    other_state = build_oauth_state(uuid_mod.UUID(other_id))
    second = await client.get("/api/v1/channels/oauth/callback", params={"code": "code-b", "state": other_state})
    assert "oauth_error=connect_failed" in second.headers["location"]

    blocked_logs = list(
        await db_session.scalars(
            select(AuditLog).where(AuditLog.action_type == "oauth_connect", AuditLog.result == "blocked")
        )
    )
    assert len(blocked_logs) == 1
    assert "different CreatorOS account" in blocked_logs[0].failure_reason


@pytest.mark.asyncio
async def test_kill_switch_activate_and_deactivate_are_audited(client, db_session, unique_email):
    token = await _register_and_token(client, unique_email)  # first user -> OWNER role
    headers = {"Authorization": f"Bearer {token}"}

    activate = await client.post(
        "/api/v1/settings/kill-switch/activate", json={"reason": "testing"}, headers=headers
    )
    assert activate.status_code == 200
    deactivate = await client.post("/api/v1/settings/kill-switch/deactivate", headers=headers)
    assert deactivate.status_code == 200

    activate_logs = list(
        await db_session.scalars(select(AuditLog).where(AuditLog.action_type == "kill_switch_activate"))
    )
    deactivate_logs = list(
        await db_session.scalars(select(AuditLog).where(AuditLog.action_type == "kill_switch_deactivate"))
    )
    assert len(activate_logs) == 1
    assert len(deactivate_logs) == 1
