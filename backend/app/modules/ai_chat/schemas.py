from pydantic import BaseModel, Field


class AIChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8000)
    system_prompt: str | None = Field(default=None, max_length=4000)
    # Explicit provider/model selection, per app.ai.orchestrator's registry
    # (currently "ollama" | "openai" | "openrouter"). Both default to the
    # server's configured AI_PRIMARY_PROVIDER/AI_FALLBACK_PROVIDER chain --
    # a caller never has to know what's configured to get a normal response.
    provider: str | None = None
    model: str | None = None
    temperature: float = Field(default=0.4, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1000, ge=1, le=8000)


class AIChatResponse(BaseModel):
    success: bool
    provider: str
    model: str
    response: str
