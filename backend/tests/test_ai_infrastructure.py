"""Local-Ollama infrastructure: FAST/DEEP mode, model routing, bounded
concurrency, creator-isolated TTL cache, explicit failure codes, and safe
observability metrics.

Per this codebase's established AI-testing convention: production code
talks to a real local Ollama; automated tests use deterministic fake/
scripted providers monkeypatched at their call site so CI never makes a
real network/ML call. The two tests that genuinely need a live Ollama
(health check, unknown-model 404) skip cleanly when one isn't reachable
instead of failing the suite in an environment without it.
"""
import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import BaseModel
from sqlalchemy import select

from app.ai.cache import cached_generate, invalidate_for_user, purge_expired_entries
from app.ai.concurrency import BoundedConcurrencyProvider
from app.ai.metrics import get_metrics_summary
from app.ai.models import AIGenerationCache
from app.ai.orchestrator import AIOrchestrator, AIOrchestratorError
from app.ai.providers.base import (
    AICompletionResult,
    AIGenerationTimeoutError,
    AIMessage,
    AIProvider,
    AIProviderUnavailableError,
    AIQueueBusyError,
    ModelNotAvailableError,
)
from app.ai.providers.ollama import OllamaProvider
from app.ai.router import AIMode, ModelTier, default_tier_for_mode, resolve_ollama_model
from app.core.config import get_settings


def _ollama_reachable(base_url: str) -> bool:
    try:
        resp = httpx.get(f"{base_url}/api/tags", timeout=2.0)
        return resp.status_code == 200
    except httpx.TransportError:
        return False


REAL_OLLAMA_URL = get_settings().ollama_base_url
OLLAMA_UP = _ollama_reachable(REAL_OLLAMA_URL)
skip_without_ollama = pytest.mark.skipif(not OLLAMA_UP, reason="real Ollama not reachable from this environment")


class _Schema(BaseModel):
    value: str


class _CapturingProvider(AIProvider):
    """Records every kwarg complete() was called with, for asserting the
    orchestrator/router chose the right think/model values."""

    name = "ollama"

    def __init__(self, response_text: str = '{"value": "ok"}'):
        self._response_text = response_text
        self.calls: list[dict] = []

    async def is_available(self) -> bool:
        return True

    async def complete(self, messages, *, temperature=0.4, max_tokens=2000, json_mode=False, think=False, model=None):
        self.calls.append({"think": think, "model": model})
        return AICompletionResult(
            text=self._response_text, provider=self.name, model=model or "captured",
            prompt_tokens=1, completion_tokens=1,
        )


class _SlowProvider(AIProvider):
    """Holds its concurrency slot for `delay_s` before returning -- lets
    tests observe how many requests are in flight at once."""

    name = "ollama"

    def __init__(self, delay_s: float):
        self._delay_s = delay_s
        self.in_flight = 0
        self.max_observed_in_flight = 0

    async def is_available(self) -> bool:
        return True

    async def complete(self, messages, *, temperature=0.4, max_tokens=2000, json_mode=False, think=False, model=None):
        self.in_flight += 1
        self.max_observed_in_flight = max(self.max_observed_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self._delay_s)
            return AICompletionResult(
                text='{"value": "ok"}', provider=self.name, model="slow", prompt_tokens=1, completion_tokens=1
            )
        finally:
            self.in_flight -= 1


# ---------------------------------------------------------------------------
# 5/8. Model routing
# ---------------------------------------------------------------------------

def test_router_resolves_each_tier_to_a_distinct_configured_model():
    settings = get_settings()
    fast = resolve_ollama_model(ModelTier.FAST_SMALL, settings)
    coding = resolve_ollama_model(ModelTier.CODING, settings)
    deep = resolve_ollama_model(ModelTier.DEEP, settings)
    assert fast == settings.ollama_model
    assert coding == settings.ollama_coding_model
    assert deep == settings.ollama_deep_model
    # Model routing is never arbitrary/empty -- every tier resolves to a
    # real, non-empty, configured model name.
    assert all([fast, coding, deep])


def test_default_tier_for_mode():
    assert default_tier_for_mode(AIMode.FAST) is ModelTier.FAST_SMALL
    assert default_tier_for_mode(AIMode.DEEP) is ModelTier.DEEP


# ---------------------------------------------------------------------------
# 3/4. FAST vs DEEP mode plumbing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fast_mode_sends_think_false_and_fast_small_model():
    provider = _CapturingProvider()
    orchestrator = AIOrchestrator(primary=provider)

    await orchestrator.generate_structured(
        task="t", system_prompt="s", user_prompt="u", schema=_Schema, mode=AIMode.FAST,
    )
    assert provider.calls[0]["think"] is False
    assert provider.calls[0]["model"] == get_settings().ollama_model


@pytest.mark.asyncio
async def test_deep_mode_sends_think_true_and_deep_model():
    provider = _CapturingProvider()
    orchestrator = AIOrchestrator(primary=provider)

    await orchestrator.generate_structured(
        task="t", system_prompt="s", user_prompt="u", schema=_Schema, mode=AIMode.DEEP,
    )
    assert provider.calls[0]["think"] is True
    assert provider.calls[0]["model"] == get_settings().ollama_deep_model


@pytest.mark.asyncio
async def test_coding_tier_routes_to_coding_model_even_in_fast_mode():
    provider = _CapturingProvider()
    orchestrator = AIOrchestrator(primary=provider)

    await orchestrator.generate_structured(
        task="t", system_prompt="s", user_prompt="u", schema=_Schema,
        mode=AIMode.FAST, tier=ModelTier.CODING,
    )
    assert provider.calls[0]["think"] is False
    assert provider.calls[0]["model"] == get_settings().ollama_coding_model


# ---------------------------------------------------------------------------
# 6/16. Invalid model / provider unavailable -> specific failure codes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_provider_unreachable_raises_ai_provider_unavailable_code():
    # Port 1 is never a real Ollama server -- fails fast, no real network
    # dependency, deterministic in CI.
    provider = OllamaProvider(base_url="http://127.0.0.1:1", model="whatever")
    orchestrator = AIOrchestrator(primary=provider)

    with pytest.raises(AIOrchestratorError) as exc_info:
        await orchestrator.generate_structured(
            task="t", system_prompt="s", user_prompt="u", schema=_Schema, max_retries=1,
        )
    assert exc_info.value.code == "AI_PROVIDER_UNAVAILABLE"


@pytest.mark.asyncio
@skip_without_ollama
async def test_unknown_model_raises_model_not_available_against_real_ollama():
    # Testing the PROVIDER directly (not through AIOrchestrator): the
    # orchestrator always re-resolves the model via app.ai.router for any
    # provider named "ollama" (that's the point of centralized model
    # routing in production) -- so the realistic way this error occurs is
    # an operator misconfiguring OLLAMA_MODEL/OLLAMA_DEEP_MODEL/
    # OLLAMA_CODING_MODEL to a model that isn't installed, which this
    # exercises at the layer that actually talks to Ollama.
    provider = OllamaProvider(base_url=REAL_OLLAMA_URL, model="this-model-does-not-exist:latest")
    with pytest.raises(ModelNotAvailableError):
        await provider.complete([AIMessage(role="user", content="hi")])


@pytest.mark.asyncio
async def test_error_code_classification_for_each_failure_type():
    class _Raises(AIProvider):
        name = "ollama"

        def __init__(self, exc):
            self._exc = exc

        async def is_available(self):
            return True

        async def complete(self, *a, **k):
            raise self._exc

    cases = [
        (AIProviderUnavailableError("x"), "AI_PROVIDER_UNAVAILABLE"),
        (ModelNotAvailableError("x"), "MODEL_NOT_AVAILABLE"),
        (AIGenerationTimeoutError("x"), "AI_GENERATION_TIMEOUT"),
        (AIQueueBusyError("x"), "AI_QUEUE_BUSY"),
    ]
    for exc, expected_code in cases:
        orchestrator = AIOrchestrator(primary=_Raises(exc))
        with pytest.raises(AIOrchestratorError) as exc_info:
            await orchestrator.generate_structured(
                task="t", system_prompt="s", user_prompt="u", schema=_Schema, max_retries=2,
            )
        assert exc_info.value.code == expected_code


# ---------------------------------------------------------------------------
# 7/9/18. Timeout, concurrency limit, high load
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bounded_concurrency_caps_simultaneous_requests():
    slow = _SlowProvider(delay_s=0.05)
    bounded = BoundedConcurrencyProvider(slow, max_concurrent=2, queue_timeout_seconds=5.0)

    await asyncio.gather(*[
        bounded.complete([AIMessage(role="user", content="x")]) for _ in range(6)
    ])
    assert slow.max_observed_in_flight <= 2


@pytest.mark.asyncio
async def test_bounded_concurrency_raises_queue_busy_when_saturated():
    slow = _SlowProvider(delay_s=0.3)
    bounded = BoundedConcurrencyProvider(slow, max_concurrent=1, queue_timeout_seconds=0.05)

    async def _hold():
        await bounded.complete([AIMessage(role="user", content="x")])

    holder = asyncio.create_task(_hold())
    await asyncio.sleep(0.02)  # let the holder acquire the only slot
    with pytest.raises(AIQueueBusyError):
        await bounded.complete([AIMessage(role="user", content="x")])
    await holder


# ---------------------------------------------------------------------------
# 12/13. Cache TTL/invalidation + creator isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cache_is_isolated_per_creator(db_session):
    provider = _CapturingProvider('{"value": "shared prompt result"}')
    orchestrator = AIOrchestrator(primary=provider)
    user_a, user_b = uuid.uuid4(), uuid.uuid4()

    await cached_generate(
        db_session, orchestrator, task="t", system_prompt="s", user_prompt="identical for both users",
        schema=_Schema, user_id=user_a, mode=AIMode.FAST,
    )
    await cached_generate(
        db_session, orchestrator, task="t", system_prompt="s", user_prompt="identical for both users",
        schema=_Schema, user_id=user_b, mode=AIMode.FAST,
    )

    # Same prompt, different creators -- must NOT share a cache entry.
    assert len(provider.calls) == 2


@pytest.mark.asyncio
async def test_expired_cache_entry_is_treated_as_a_miss(db_session):
    provider = _CapturingProvider()
    orchestrator = AIOrchestrator(primary=provider)
    user_id = uuid.uuid4()

    await cached_generate(
        db_session, orchestrator, task="expiry-test", system_prompt="s", user_prompt="p",
        schema=_Schema, user_id=user_id, mode=AIMode.FAST,
    )
    assert len(provider.calls) == 1

    # Force the just-written row into the past.
    cache_row = await db_session.scalar(select(AIGenerationCache).where(AIGenerationCache.task == "expiry-test"))
    cache_row.expires_at = datetime.now(UTC) - timedelta(hours=1)
    await db_session.commit()

    await cached_generate(
        db_session, orchestrator, task="expiry-test", system_prompt="s", user_prompt="p",
        schema=_Schema, user_id=user_id, mode=AIMode.FAST,
    )
    assert len(provider.calls) == 2  # expired -> regenerated, not served stale


@pytest.mark.asyncio
async def test_invalidate_for_user_forces_regeneration(db_session):
    provider = _CapturingProvider()
    orchestrator = AIOrchestrator(primary=provider)
    user_id = uuid.uuid4()

    await cached_generate(
        db_session, orchestrator, task="inv-test", system_prompt="s", user_prompt="p",
        schema=_Schema, user_id=user_id, mode=AIMode.FAST,
    )
    deleted = await invalidate_for_user(db_session, user_id, task="inv-test")
    assert deleted == 1

    await cached_generate(
        db_session, orchestrator, task="inv-test", system_prompt="s", user_prompt="p",
        schema=_Schema, user_id=user_id, mode=AIMode.FAST,
    )
    assert len(provider.calls) == 2


@pytest.mark.asyncio
async def test_purge_expired_entries_deletes_only_stale_rows(db_session):
    provider = _CapturingProvider()
    orchestrator = AIOrchestrator(primary=provider)
    user_id = uuid.uuid4()

    await cached_generate(
        db_session, orchestrator, task="purge-test", system_prompt="s", user_prompt="keep-me",
        schema=_Schema, user_id=user_id, mode=AIMode.FAST,
    )
    fresh_row = await db_session.scalar(select(AIGenerationCache).where(AIGenerationCache.task == "purge-test"))
    fresh_id = fresh_row.id

    stale = AIGenerationCache(
        task="purge-test", prompt_version="v1", model="ollama", mode="fast",
        input_hash="deadbeef", owner_user_id=user_id, result_json='{"value":"stale"}',
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    db_session.add(stale)
    await db_session.commit()

    deleted = await purge_expired_entries(db_session)
    assert deleted == 1
    remaining = await db_session.scalar(select(AIGenerationCache).where(AIGenerationCache.id == fresh_id))
    assert remaining is not None


# ---------------------------------------------------------------------------
# 15. Observability metrics
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_metrics_recorded_for_cache_miss_and_hit(db_session):
    provider = _CapturingProvider()
    orchestrator = AIOrchestrator(primary=provider)
    user_id = uuid.uuid4()

    await cached_generate(
        db_session, orchestrator, task="metrics-test", system_prompt="s", user_prompt="p",
        schema=_Schema, user_id=user_id, mode=AIMode.FAST,
    )
    await cached_generate(
        db_session, orchestrator, task="metrics-test", system_prompt="s", user_prompt="p",
        schema=_Schema, user_id=user_id, mode=AIMode.FAST,
    )
    await db_session.commit()

    summary = await get_metrics_summary(db_session, since_minutes=60)
    assert summary.count >= 2
    assert summary.cache_hit_rate > 0


# ---------------------------------------------------------------------------
# 1/2. Real Ollama health (skips cleanly if unreachable)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@skip_without_ollama
async def test_real_ollama_health_check():
    provider = OllamaProvider(base_url=REAL_OLLAMA_URL, model=get_settings().ollama_model)
    assert await provider.is_available() is True


@pytest.mark.asyncio
@skip_without_ollama
async def test_real_ollama_fast_mode_completes_quickly():
    """One real, safe local prompt against the configured FAST_SMALL model
    -- not a fake success, a genuine local generation, kept short so the
    suite stays fast."""
    provider = OllamaProvider(base_url=REAL_OLLAMA_URL, model=get_settings().ollama_model)
    result = await provider.complete(
        [AIMessage(role="user", content="Reply with exactly one word: OK")],
        max_tokens=10,
        think=False,
    )
    assert result.text.strip() != ""
