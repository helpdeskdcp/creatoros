"""Central AI orchestration layer.

Responsibilities (per the CreatorOS AI Quality Rule): model selection, prompt
assembly, structured-output validation, retries, provider fallback, and audit
logging. No module outside app/ai may construct an AIProvider directly, and
no raw AI output ever reaches a database write without passing through
generate_structured()'s Pydantic validation first.
"""
import json
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.ai.providers.base import AICompletionResult, AIMessage, AIProvider, AIProviderError
from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger("ai.orchestrator")

T = TypeVar("T", bound=BaseModel)


class AIOrchestratorError(Exception):
    """Raised when both the primary and fallback provider fail, or the model
    never produces output matching the requested schema."""


class AIOrchestrator:
    def __init__(self, primary: AIProvider, fallback: AIProvider | None = None):
        self.primary = primary
        self.fallback = fallback

    async def generate_structured(
        self,
        *,
        task: str,
        system_prompt: str,
        user_prompt: str,
        schema: type[T],
        temperature: float = 0.4,
        max_tokens: int = 2000,
        max_retries: int = 2,
    ) -> T:
        schema_hint = (
            f"Respond with ONLY a single JSON object matching this schema "
            f"(no markdown, no commentary): {schema.model_json_schema()}"
        )
        messages = [
            AIMessage(role="system", content=f"{system_prompt}\n\n{schema_hint}"),
            AIMessage(role="user", content=user_prompt),
        ]

        providers = [p for p in (self.primary, self.fallback) if p is not None]
        last_error: Exception | None = None

        for provider in providers:
            for attempt in range(1, max_retries + 1):
                try:
                    result = await provider.complete(
                        messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        json_mode=True,
                    )
                    parsed = _parse_and_validate(result, schema)
                    logger.info(
                        "ai_generation_succeeded",
                        task=task,
                        provider=provider.name,
                        attempt=attempt,
                        prompt_tokens=result.prompt_tokens,
                        completion_tokens=result.completion_tokens,
                    )
                    return parsed
                except (AIProviderError, ValidationError, json.JSONDecodeError, KeyError) as exc:
                    last_error = exc
                    logger.warning(
                        "ai_generation_attempt_failed",
                        task=task,
                        provider=provider.name,
                        attempt=attempt,
                        error=str(exc),
                    )
                    messages.append(
                        AIMessage(
                            role="user",
                            content=(
                                "Your previous response was invalid: "
                                f"{exc}. Reply again with ONLY valid JSON matching the schema."
                            ),
                        )
                    )

        logger.error("ai_generation_failed", task=task, error=str(last_error))
        raise AIOrchestratorError(
            f"AI generation for task '{task}' failed on every provider/attempt: {last_error}"
        )


def _parse_and_validate(result: AICompletionResult, schema: type[T]) -> T:
    text = result.text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    data = json.loads(text)
    return schema.model_validate(data)


def build_orchestrator(settings: Settings | None = None) -> AIOrchestrator:
    settings = settings or get_settings()
    from app.ai.providers.ollama import OllamaProvider
    from app.ai.providers.openai_compat import OpenAICompatProvider

    providers: dict[str, AIProvider] = {
        "ollama": OllamaProvider(settings.ollama_base_url, settings.ollama_model),
        "openai": OpenAICompatProvider(
            settings.openai_base_url, settings.openai_api_key, settings.openai_model
        ),
    }

    primary = providers.get(settings.ai_primary_provider, providers["ollama"])
    fallback = providers.get(settings.ai_fallback_provider) if settings.ai_fallback_provider else None
    return AIOrchestrator(primary=primary, fallback=fallback)
