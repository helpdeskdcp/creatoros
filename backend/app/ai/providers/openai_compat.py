"""AIProvider for OpenAI and any OpenAI-compatible chat-completions API
(vLLM, together.ai, groq, etc. all speak this same wire format)."""
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


class OpenAICompatProvider(AIProvider):
    name = "openai"

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model

    async def is_available(self) -> bool:
        return bool(self._api_key)

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
        # `think` (Ollama's qwen3 "extended reasoning" toggle) has no
        # equivalent on a plain chat-completions model like gpt-4o-mini --
        # accepted for interface compatibility with AIProvider, ignored here.
        if not self._api_key:
            raise AIProviderUnavailableError("OPENAI_API_KEY is not configured")

        resolved_model = model or self._model
        payload = {
            "model": resolved_model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{self._base_url}/chat/completions", json=payload, headers=headers
                )
        except httpx.ReadTimeout as exc:
            raise AIGenerationTimeoutError(
                f"{self._base_url} did not respond within 60s"
            ) from exc
        except httpx.TransportError as exc:
            raise AIProviderUnavailableError(
                f"OpenAI-compatible endpoint unreachable: {self._base_url}"
            ) from exc

        if resp.status_code == 404:
            raise ModelNotAvailableError(f"Model '{resolved_model}' is not available at {self._base_url}")
        if resp.status_code != 200:
            raise AIProviderError(f"OpenAI-compatible API returned {resp.status_code}: {resp.text}")

        body = resp.json()
        choice = body["choices"][0]["message"]["content"]
        usage = body.get("usage", {})
        return AICompletionResult(
            text=choice,
            provider=self.name,
            model=resolved_model,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )
