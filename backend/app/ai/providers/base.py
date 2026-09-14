"""AIProvider: the single interface all LLM calls go through.

Business logic (hooks/titles/scripts/SEO/etc.) never imports an LLM SDK or
calls a provider's HTTP API directly — it calls AIOrchestrator, which calls
whichever AIProvider is configured. This is what lets CreatorOS swap Ollama
for OpenAI (or add a third provider) without touching a single content-engine
module.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class AIMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class AICompletionResult:
    text: str
    provider: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None


class AIProviderError(Exception):
    """Raised on transport/auth/rate-limit failure. Orchestrator decides
    whether to retry or fall back to a secondary provider."""


class AIProviderUnavailableError(AIProviderError):
    """The provider itself could not be reached at all (connection refused,
    DNS failure, transport error) -- distinct from a request that reached
    the provider and failed. Surfaces to callers as AI_PROVIDER_UNAVAILABLE."""


class ModelNotAvailableError(AIProviderError):
    """The provider was reachable but the requested model is not installed/
    loadable there. Surfaces to callers as MODEL_NOT_AVAILABLE."""


class AIGenerationTimeoutError(AIProviderError):
    """The provider did not respond within the configured timeout. Surfaces
    to callers as AI_GENERATION_TIMEOUT."""


class AIQueueBusyError(AIProviderError):
    """The local concurrency gate is saturated and the request timed out
    waiting for a worker slot rather than for the model itself. Surfaces to
    callers as AI_QUEUE_BUSY. Never raised by an external provider (only
    the bounded-concurrency wrapper around a local provider)."""


class RateLimitedError(AIProviderError):
    """The provider responded with HTTP 429 (its own rate limit, not this
    app's local concurrency gate). Surfaces to callers as AI_RATE_LIMITED.
    Treated like AIProviderUnavailableError for retry purposes -- resending
    the identical request immediately won't succeed, so the orchestrator
    moves straight to a fallback provider (if any) instead of retrying."""


class AIProvider(ABC):
    name: str

    @abstractmethod
    async def complete(
        self,
        messages: list[AIMessage],
        *,
        temperature: float = 0.4,
        max_tokens: int = 2000,
        json_mode: bool = False,
        think: bool = False,
        model: str | None = None,
    ) -> AICompletionResult:
        """`think` requests extended reasoning (Ollama's qwen3-family
        "thinking" mode) when the provider/model supports it. FAST mode
        (the CreatorOS default for every routine task) always passes
        think=False; DEEP mode passes True. A provider that has no concept
        of extended thinking (e.g. plain OpenAI chat models) simply ignores
        the flag rather than erroring.

        `model` overrides the provider's configured default model for this
        one call -- how app.ai.router's per-tier model routing reaches a
        provider without constructing a separate provider instance per
        tier."""
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """Cheap health check used by the orchestrator before routing to this
        provider, so a down provider fails over instead of timing out a
        user-facing request."""
