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

from app.ai.providers.base import (
    AICompletionResult,
    AIGenerationTimeoutError,
    AIMessage,
    AIProvider,
    AIProviderError,
    AIProviderUnavailableError,
    AIQueueBusyError,
    ModelNotAvailableError,
)
from app.ai.router import AIMode, ModelTier, default_tier_for_mode, resolve_ollama_model
from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger("ai.orchestrator")

T = TypeVar("T", bound=BaseModel)

# Maps a failed provider's exception type to the stable, documented failure
# code CreatorOS callers/observability can branch on -- never a raw
# exception message, which can vary between providers and Ollama versions.
_ERROR_CODES: dict[type[Exception], str] = {
    AIProviderUnavailableError: "AI_PROVIDER_UNAVAILABLE",
    ModelNotAvailableError: "MODEL_NOT_AVAILABLE",
    AIGenerationTimeoutError: "AI_GENERATION_TIMEOUT",
    AIQueueBusyError: "AI_QUEUE_BUSY",
}


def _error_code_for(exc: Exception | None) -> str:
    if exc is None:
        return "AI_GENERATION_FAILED"
    for exc_type, code in _ERROR_CODES.items():
        if isinstance(exc, exc_type):
            return code
    return "AI_GENERATION_FAILED"


class AIOrchestratorError(Exception):
    """Raised when both the primary and fallback provider fail, or the model
    never produces output matching the requested schema. `.code` is one of
    the stable AI_* failure codes -- callers should branch on that, not on
    exception message text."""

    def __init__(self, message: str, code: str = "AI_GENERATION_FAILED"):
        super().__init__(message)
        self.code = code


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
        mode: AIMode = AIMode.FAST,
        tier: ModelTier | None = None,
        temperature: float = 0.4,
        max_tokens: int = 2000,
        max_retries: int = 2,
    ) -> tuple[T, AICompletionResult]:
        """FAST (default) never enables extended thinking -- every routine
        CreatorOS generation/classification task uses this. DEEP
        (mode=AIMode.DEEP) enables it for the minority of tasks that
        genuinely need extended reasoning, and only ever targets a
        thinking-capable model (see app.ai.router).

        Returns (parsed_result, raw_completion) -- the raw completion is
        needed by callers that record token-count metrics without forcing
        every call site to re-derive it.
        """
        resolved_tier = tier or default_tier_for_mode(mode)
        think = mode is AIMode.DEEP

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
            # Model-tier routing is Ollama-specific (see app/ai/router.py) --
            # an OpenAI-compatible provider always uses its own configured
            # model; there is no local-CPU tiering concern for a hosted API.
            model_override = (
                resolve_ollama_model(resolved_tier, get_settings())
                if provider.name == "ollama"
                else None
            )
            for attempt in range(1, max_retries + 1):
                try:
                    result = await provider.complete(
                        messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        json_mode=True,
                        think=think,
                        model=model_override,
                    )
                    parsed = _parse_and_validate(result, schema)
                    logger.info(
                        "ai_generation_succeeded",
                        task=task,
                        provider=provider.name,
                        model=result.model,
                        mode=mode.value,
                        attempt=attempt,
                        prompt_tokens=result.prompt_tokens,
                        completion_tokens=result.completion_tokens,
                    )
                    return parsed, result
                except (AIProviderError, ValidationError, json.JSONDecodeError, KeyError) as exc:
                    last_error = exc
                    logger.warning(
                        "ai_generation_attempt_failed",
                        task=task,
                        provider=provider.name,
                        mode=mode.value,
                        attempt=attempt,
                        error=str(exc),
                    )
                    # A provider that is unreachable, missing the model, or
                    # queue-saturated will not fix itself within the same
                    # request -- move straight to the fallback provider (if
                    # any) instead of burning the remaining retry budget
                    # resending an identical doomed request.
                    if isinstance(
                        exc, AIProviderUnavailableError | ModelNotAvailableError | AIQueueBusyError
                    ):
                        break
                    messages.append(
                        AIMessage(
                            role="user",
                            content=(
                                "Your previous response was invalid: "
                                f"{exc}. Reply again with ONLY valid JSON matching the schema."
                            ),
                        )
                    )

        logger.error("ai_generation_failed", task=task, mode=mode.value, error=str(last_error))
        raise AIOrchestratorError(
            f"AI generation for task '{task}' failed on every provider/attempt: {last_error}",
            code=_error_code_for(last_error),
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
    from app.ai.concurrency import BoundedConcurrencyProvider
    from app.ai.providers.ollama import OllamaProvider
    from app.ai.providers.openai_compat import OpenAICompatProvider

    # Bounded concurrency only applies to the local Ollama provider -- a
    # hosted OpenAI-compatible API has its own server-side capacity and
    # rate limiting; CreatorOS doesn't need to additionally throttle it.
    ollama_provider: AIProvider = BoundedConcurrencyProvider(
        OllamaProvider(settings.ollama_base_url, settings.ollama_model),
        max_concurrent=settings.ollama_max_concurrent_requests,
        queue_timeout_seconds=settings.ollama_queue_wait_timeout_seconds,
    )

    providers: dict[str, AIProvider] = {
        "ollama": ollama_provider,
        "openai": OpenAICompatProvider(
            settings.openai_base_url, settings.openai_api_key, settings.openai_model
        ),
    }

    primary = providers.get(settings.ai_primary_provider, providers["ollama"])
    fallback = providers.get(settings.ai_fallback_provider) if settings.ai_fallback_provider else None
    return AIOrchestrator(primary=primary, fallback=fallback)
