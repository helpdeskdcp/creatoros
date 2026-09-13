"""AIProvider backed by a local Ollama server. Preferred default: free, no
external data egress, and cheap enough to use for every routine classification
or generation task (see docs/ai.md — AI Cost Control)."""
import httpx

from app.ai.providers.base import (
    AICompletionResult,
    AIGenerationTimeoutError,
    AIMessage,
    AIProvider,
    AIProviderError,
    AIProviderUnavailableError,
    ModelNotAvailableError,
)

# Generation can legitimately take tens of seconds on a CPU-only host in
# DEEP (think=true) mode -- 32s+ was observed in production benchmarking
# (scripts/benchmark_ollama.py) for a trivial prompt. 180s gives real DEEP
# requests room without leaving a hung TCP connection open indefinitely.
_REQUEST_TIMEOUT_S = 180.0
_HEALTH_TIMEOUT_S = 3.0


class OllamaProvider(AIProvider):
    name = "ollama"

    def __init__(self, base_url: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=_HEALTH_TIMEOUT_S) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
            return resp.status_code == 200
        except httpx.TransportError:
            return False

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
        resolved_model = model or self._model
        payload = {
            "model": resolved_model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "think": think,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if json_mode:
            payload["format"] = "json"

        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_S) as client:
                resp = await client.post(f"{self._base_url}/api/chat", json=payload)
        except httpx.ConnectTimeout as exc:
            raise AIProviderUnavailableError(f"Ollama unreachable at {self._base_url}") from exc
        except httpx.ReadTimeout as exc:
            raise AIGenerationTimeoutError(
                f"Ollama did not respond within {_REQUEST_TIMEOUT_S}s for model {resolved_model}"
            ) from exc
        except httpx.TransportError as exc:
            raise AIProviderUnavailableError(f"Ollama unreachable at {self._base_url}") from exc

        if resp.status_code == 404:
            raise ModelNotAvailableError(f"Model '{resolved_model}' is not available on this Ollama server")
        if resp.status_code == 400 and "does not support thinking" in resp.text:
            raise ModelNotAvailableError(
                f"Model '{resolved_model}' does not support DEEP (thinking) mode"
            )
        if resp.status_code != 200:
            raise AIProviderError(f"Ollama returned {resp.status_code}: {resp.text}")

        body = resp.json()
        content = body.get("message", {}).get("content", "")
        return AICompletionResult(
            text=content,
            provider=self.name,
            model=resolved_model,
            prompt_tokens=body.get("prompt_eval_count"),
            completion_tokens=body.get("eval_count"),
        )
