"""AIProvider backed by a local Ollama server. Preferred default: free, no
external data egress, and cheap enough to use for every routine classification
or generation task (see docs/ai.md — AI Cost Control)."""
import httpx

from app.ai.providers.base import AICompletionResult, AIMessage, AIProvider, AIProviderError


class OllamaProvider(AIProvider):
    name = "ollama"

    def __init__(self, base_url: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
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
    ) -> AICompletionResult:
        payload = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if json_mode:
            payload["format"] = "json"

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(f"{self._base_url}/api/chat", json=payload)
        except httpx.TransportError as exc:
            raise AIProviderError(f"Ollama unreachable at {self._base_url}") from exc

        if resp.status_code != 200:
            raise AIProviderError(f"Ollama returned {resp.status_code}: {resp.text}")

        body = resp.json()
        content = body.get("message", {}).get("content", "")
        return AICompletionResult(
            text=content,
            provider=self.name,
            model=self._model,
            prompt_tokens=body.get("prompt_eval_count"),
            completion_tokens=body.get("eval_count"),
        )
