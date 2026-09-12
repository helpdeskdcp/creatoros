import json

import pytest
from pydantic import BaseModel

from app.ai.cache import cached_generate
from app.ai.orchestrator import AIOrchestrator
from app.ai.providers.base import AICompletionResult, AIProvider


class _CountingProvider(AIProvider):
    name = "counting"

    def __init__(self, response: dict):
        self._response = response
        self.calls = 0

    async def is_available(self) -> bool:
        return True

    async def complete(self, messages, *, temperature=0.4, max_tokens=2000, json_mode=False):
        self.calls += 1
        return AICompletionResult(
            text=json.dumps(self._response), provider=self.name, model="counting-1",
            prompt_tokens=1, completion_tokens=1,
        )


class _Schema(BaseModel):
    title: str


@pytest.mark.asyncio
async def test_cached_generate_hits_cache_on_identical_input(db_session):
    provider = _CountingProvider({"title": "Cached Result"})
    orchestrator = AIOrchestrator(primary=provider)

    first = await cached_generate(
        db_session, orchestrator, task="t", system_prompt="sys", user_prompt="same input", schema=_Schema,
    )
    second = await cached_generate(
        db_session, orchestrator, task="t", system_prompt="sys", user_prompt="same input", schema=_Schema,
    )

    assert first.title == "Cached Result"
    assert second.title == "Cached Result"
    assert provider.calls == 1  # second call must be served from cache, not the provider


@pytest.mark.asyncio
async def test_cached_generate_misses_cache_on_different_input(db_session):
    provider = _CountingProvider({"title": "X"})
    orchestrator = AIOrchestrator(primary=provider)

    await cached_generate(
        db_session, orchestrator, task="t", system_prompt="sys", user_prompt="input A", schema=_Schema,
    )
    await cached_generate(
        db_session, orchestrator, task="t", system_prompt="sys", user_prompt="input B", schema=_Schema,
    )

    assert provider.calls == 2


@pytest.mark.asyncio
async def test_cached_generate_respects_prompt_version(db_session):
    provider = _CountingProvider({"title": "X"})
    orchestrator = AIOrchestrator(primary=provider)

    await cached_generate(
        db_session, orchestrator, task="t", system_prompt="sys", user_prompt="same",
        schema=_Schema, prompt_version="v1",
    )
    await cached_generate(
        db_session, orchestrator, task="t", system_prompt="sys", user_prompt="same",
        schema=_Schema, prompt_version="v2",
    )

    assert provider.calls == 2  # bumping prompt_version must invalidate the old cache entry
