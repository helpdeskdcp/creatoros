"""Creator-specific learning loop: concluded experiments (real measured
winners) turn into persistent per-creator signals, and those signals
actually get read back into future AI-generation prompts -- never an
LLM's self-reported guess standing in for real historical performance."""
import json
import uuid

import pytest
from sqlalchemy import select

from app.ai.dependency import get_orchestrator
from app.ai.orchestrator import AIOrchestrator
from app.ai.providers.base import AICompletionResult, AIProvider
from app.main import app
from app.modules.experiments import service as experiments_service
from app.modules.experiments.learning import get_learning_context_text, record_experiment_outcome
from app.modules.experiments.models import CreatorLearningSignal
from app.modules.users.models import User, UserRole


@pytest.mark.asyncio
async def test_record_experiment_outcome_credits_winner_only_keywords(db_session):
    user = User(email="learn1@example.com", hashed_password="x", role=UserRole.OWNER)
    db_session.add(user)
    await db_session.flush()

    experiment = await experiments_service.create_experiment(
        db_session, user.id, "title", "h", "ctr", None, 10,
        ["Boring plain update", "The secret nobody tells you"],
    )
    winner = experiment.variants[1]  # "The secret nobody tells you"
    experiment.status = experiment.status.RUNNING
    experiment.winning_variant_id = winner.id
    await db_session.commit()

    await record_experiment_outcome(db_session, experiment)

    signals = list(
        await db_session.scalars(
            select(CreatorLearningSignal).where(
                CreatorLearningSignal.owner_user_id == user.id,
                CreatorLearningSignal.signal_type == "title_keyword",
            )
        )
    )
    by_key = {s.signal_key: s for s in signals}
    assert by_key["secret"].wins == 1
    assert by_key["secret"].losses == 0
    assert by_key["boring"].losses == 1
    assert by_key["boring"].wins == 0
    # "tells" appears only in the winner too -- also a win, not skipped.
    assert by_key["tells"].wins == 1


@pytest.mark.asyncio
async def test_get_learning_context_requires_minimum_sample(db_session):
    user = User(email="learn2@example.com", hashed_password="x", role=UserRole.OWNER)
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        CreatorLearningSignal(owner_user_id=user.id, signal_type="title_keyword", signal_key="secret", wins=1, losses=0)
    )
    await db_session.commit()

    # Only 1 total occurrence -- below _MIN_TOTAL_FOR_CONTEXT, must not surface.
    context = await get_learning_context_text(db_session, user.id, signal_type="title_keyword")
    assert context is None


@pytest.mark.asyncio
async def test_get_learning_context_surfaces_real_winners(db_session):
    user = User(email="learn3@example.com", hashed_password="x", role=UserRole.OWNER)
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        CreatorLearningSignal(owner_user_id=user.id, signal_type="title_keyword", signal_key="secret", wins=3, losses=1)
    )
    db_session.add(
        CreatorLearningSignal(owner_user_id=user.id, signal_type="title_keyword", signal_key="boring", wins=0, losses=3)
    )
    await db_session.commit()

    context = await get_learning_context_text(db_session, user.id, signal_type="title_keyword")

    assert context is not None
    assert "secret" in context
    assert "boring" not in context  # only real winners are surfaced, not underperformers
    assert "3/4" in context


@pytest.mark.asyncio
async def test_get_learning_context_returns_none_with_no_history(db_session):
    user = User(email="learn4@example.com", hashed_password="x", role=UserRole.OWNER)
    db_session.add(user)
    await db_session.commit()

    context = await get_learning_context_text(db_session, user.id)
    assert context is None


class _CapturingProvider(AIProvider):
    """Fake AI provider that records the exact prompt it received, so
    tests can assert the learning context actually reached the model
    instead of just existing in the database unused."""

    name = "capturing-test-provider"

    def __init__(self, response_json: dict):
        self.received_messages = None
        self._response_json = response_json

    async def is_available(self) -> bool:
        return True

    async def complete(self, messages, *, temperature=0.4, max_tokens=2000, json_mode=False):
        self.received_messages = messages
        return AICompletionResult(
            text=json.dumps(self._response_json), provider=self.name, model="capturing-1",
            prompt_tokens=1, completion_tokens=1,
        )


@pytest.mark.asyncio
async def test_generate_titles_includes_real_learning_context_in_prompt(client, db_session):
    email = f"learn-titles-{uuid.uuid4().hex[:8]}@example.com"
    register = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "supersecurepassword1"}
    )
    token = register.json()["access_token"]
    user_id = register.json()["user"]["id"]

    db_session.add(
        CreatorLearningSignal(
            owner_user_id=uuid.UUID(user_id), signal_type="title_keyword", signal_key="secret", wins=4, losses=0,
        )
    )
    await db_session.commit()

    provider = _CapturingProvider({"titles": [
        {"text": "A title", "clarity_score": 80, "specificity_score": 80, "curiosity_score": 80,
         "search_relevance_score": 80, "audience_fit_score": 80}
    ]})
    app.dependency_overrides[get_orchestrator] = lambda: AIOrchestrator(primary=provider)
    try:
        resp = await client.post(
            "/api/v1/titles/generate",
            json={"topic": "growing a channel", "count": 1},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
    finally:
        app.dependency_overrides.pop(get_orchestrator, None)

    assert provider.received_messages is not None
    user_message = next(m for m in provider.received_messages if m.role == "user")
    assert "secret" in user_message.content
    assert "real A/B experiments" in user_message.content
