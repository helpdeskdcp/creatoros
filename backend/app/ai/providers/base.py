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
    ) -> AICompletionResult: ...

    @abstractmethod
    async def is_available(self) -> bool:
        """Cheap health check used by the orchestrator before routing to this
        provider, so a down provider fails over instead of timing out a
        user-facing request."""
