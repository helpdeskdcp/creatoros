import json

import pytest
from pydantic import BaseModel

from app.ai.orchestrator import AIOrchestrator, AIOrchestratorError
from app.ai.providers.base import AICompletionResult, AIProvider, AIProviderError


class _ScriptedProvider(AIProvider):
    name = "scripted"

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls = 0

    async def is_available(self) -> bool:
        return True

    async def complete(self, messages, *, temperature=0.4, max_tokens=2000, json_mode=False):
        self.calls += 1
        text = self._responses.pop(0)
        return AICompletionResult(
            text=text, provider=self.name, model="scripted-1", prompt_tokens=1, completion_tokens=1
        )


class _AlwaysFailsProvider(AIProvider):
    name = "broken"

    async def is_available(self) -> bool:
        return False

    async def complete(self, messages, *, temperature=0.4, max_tokens=2000, json_mode=False):
        raise AIProviderError("simulated provider outage")


class _Schema(BaseModel):
    title: str
    score: float


@pytest.mark.asyncio
async def test_generate_structured_happy_path():
    provider = _ScriptedProvider([json.dumps({"title": "Great Video", "score": 91.5})])
    orchestrator = AIOrchestrator(primary=provider)

    result = await orchestrator.generate_structured(
        task="test", system_prompt="sys", user_prompt="user", schema=_Schema
    )
    assert result.title == "Great Video"
    assert result.score == 91.5


@pytest.mark.asyncio
async def test_generate_structured_retries_on_invalid_json_then_succeeds():
    provider = _ScriptedProvider(
        ["not valid json at all", json.dumps({"title": "Fixed", "score": 50})]
    )
    orchestrator = AIOrchestrator(primary=provider)

    result = await orchestrator.generate_structured(
        task="test", system_prompt="sys", user_prompt="user", schema=_Schema, max_retries=2
    )
    assert result.title == "Fixed"
    assert provider.calls == 2


@pytest.mark.asyncio
async def test_generate_structured_falls_back_to_secondary_provider():
    primary = _AlwaysFailsProvider()
    fallback = _ScriptedProvider([json.dumps({"title": "From fallback", "score": 10})])
    orchestrator = AIOrchestrator(primary=primary, fallback=fallback)

    result = await orchestrator.generate_structured(
        task="test", system_prompt="sys", user_prompt="user", schema=_Schema, max_retries=1
    )
    assert result.title == "From fallback"


@pytest.mark.asyncio
async def test_generate_structured_raises_when_every_provider_fails():
    orchestrator = AIOrchestrator(primary=_AlwaysFailsProvider(), fallback=_AlwaysFailsProvider())

    with pytest.raises(AIOrchestratorError):
        await orchestrator.generate_structured(
            task="test", system_prompt="sys", user_prompt="user", schema=_Schema, max_retries=1
        )


@pytest.mark.asyncio
async def test_generate_structured_rejects_output_failing_schema_validation():
    # Missing required "score" field on every attempt — must never fall back
    # to a value the schema doesn't actually validate.
    provider = _ScriptedProvider([json.dumps({"title": "No score"})] * 3)
    orchestrator = AIOrchestrator(primary=provider)

    with pytest.raises(AIOrchestratorError):
        await orchestrator.generate_structured(
            task="test", system_prompt="sys", user_prompt="user", schema=_Schema, max_retries=3
        )
