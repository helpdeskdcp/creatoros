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


class PrivacyPolicyViolationError(AIProviderError):
    """The request was rejected by the workspace/account's own data-privacy
    guardrail (observed in production as OpenRouter's "Zero Data Retention"
    policy: a 404 whose body names a "ZDR violation (guardrail)"), not by
    the model itself being unavailable. Distinct from ModelNotAvailableError
    because the fix is different -- the operator must review their privacy
    policy configuration, not wait for the model to come back. This is a
    genuine safety signal, never something a caller should try to route
    around: it must never be retried against the same model, and callers
    must never fabricate a workaround or expose the raw provider policy
    text to an end user (see app.video.service's clean ZDR_POLICY_BLOCKED
    error code)."""


class InsufficientCreditsError(AIProviderError):
    """The provider responded with HTTP 402 -- this account's balance, not
    any model's availability or a privacy/guardrail decision. Distinct
    from every other AIProviderError so a billing failure is never
    misclassified as a generic provider error, a rate limit, or (most
    importantly) a ZDR/guardrail block, which would send an operator
    looking in the wrong place entirely. Account-wide, not model-specific
    -- retrying the same model, or a different one, cannot succeed until
    credits are added (see app.modules.video_generation.service's clean
    BILLING_INSUFFICIENT_CREDITS error code)."""


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
