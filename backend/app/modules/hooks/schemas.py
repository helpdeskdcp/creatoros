import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.modules.hooks.models import HookCategory


class GenerateHooksRequest(BaseModel):
    topic: str
    topic_id: uuid.UUID | None = None
    audience: str | None = None
    count: int = Field(default=6, ge=1, le=12)


class HookOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    text: str
    category: HookCategory
    hook_score: float | None
    clarity_score: float | None
    curiosity_score: float | None
    specificity_score: float | None
    audience_fit_score: float | None
    generated_by: str


class _GeneratedHook(BaseModel):
    text: str
    category: HookCategory
    clarity_score: float = Field(ge=0, le=100)
    curiosity_score: float = Field(ge=0, le=100)
    specificity_score: float = Field(ge=0, le=100)
    audience_fit_score: float = Field(ge=0, le=100)


class GeneratedHooksResponse(BaseModel):
    """The schema the AI orchestrator validates the model's JSON output
    against — never trust raw LLM text past this boundary."""

    hooks: list[_GeneratedHook]
