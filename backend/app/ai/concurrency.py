"""Bounds simultaneous in-flight requests to a local provider.

The VPS Ollama service is configured with OLLAMA_NUM_PARALLEL=1 and
OLLAMA_MAX_LOADED_MODELS=1 (CPU-only, ~2 vCPU) -- letting an unbounded
number of CreatorOS requests pile into Ollama at once would just make every
one of them slower (all fighting for the same core) instead of failing
fast. This wraps any AIProvider with a small FIFO semaphore: requests past
the concurrency limit wait up to `queue_timeout_seconds`, then fail with
AIQueueBusyError rather than queuing forever.

One shared instance per process -- do not construct a new Ollama connection
or a new semaphore per request.
"""
import asyncio
import time

from app.ai.providers.base import AICompletionResult, AIMessage, AIProvider, AIQueueBusyError


class BoundedConcurrencyProvider(AIProvider):
    def __init__(self, inner: AIProvider, max_concurrent: int, queue_timeout_seconds: float) -> None:
        self._inner = inner
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._queue_timeout_seconds = queue_timeout_seconds
        self.name = inner.name
        # Observability only (see app/ai/metrics.py) -- last call's queue
        # wait, not a running average. Safe to read from a single-threaded
        # asyncio event loop between awaits.
        self.last_queue_wait_seconds: float = 0.0

    async def is_available(self) -> bool:
        return await self._inner.is_available()

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
        start = time.perf_counter()
        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=self._queue_timeout_seconds)
        except TimeoutError as exc:
            raise AIQueueBusyError(
                f"{self._inner.name} request queue is busy "
                f"(waited {self._queue_timeout_seconds}s for a free slot)"
            ) from exc

        self.last_queue_wait_seconds = time.perf_counter() - start
        try:
            return await self._inner.complete(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=json_mode,
                think=think,
                model=model,
            )
        finally:
            self._semaphore.release()
