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
    RateLimitedError,
)


class OpenAICompatProvider(AIProvider):
    def __init__(self, base_url: str, api_key: str, model: str, name: str = "openai") -> None:
        # `name` distinguishes which OpenAI-compatible backend this instance
        # talks to (e.g. "openai" vs "openrouter") in logs, error codes, and
        # the AICompletionResult returned to callers -- multiple instances
        # of this same class back different providers in app.ai.orchestrator.
        self.name = name
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model

    async def is_available(self) -> bool:
        return bool(self._api_key)

    def _redact(self, text: str) -> str:
        """Defense in depth: strip our own API key from any upstream
        response body before it can reach an exception message or a log
        line, in case the provider ever echoes a request header back in an
        error body (seen in the wild on some OpenAI-compatible gateways)."""
        if self._api_key and self._api_key in text:
            return text.replace(self._api_key, "***REDACTED***")
        return text

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
            raise AIProviderUnavailableError(f"No API key configured for provider '{self.name}'")

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
        if resp.status_code == 429:
            retry_after = resp.headers.get("retry-after")
            suffix = f" (retry after {retry_after}s)" if retry_after else ""
            raise RateLimitedError(f"Provider '{self.name}' rate-limited this request{suffix}")
        if resp.status_code in (401, 403):
            # Never include resp.text here -- some providers echo the
            # sent Authorization header back in 401/403 error bodies.
            raise AIProviderError(f"Provider '{self.name}' rejected the request: HTTP {resp.status_code}")
        if resp.status_code != 200:
            raise AIProviderError(
                f"OpenAI-compatible API returned {resp.status_code}: {self._redact(resp.text)}"
            )

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
