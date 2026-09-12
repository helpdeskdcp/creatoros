import uuid

from pydantic import BaseModel, ConfigDict

from app.modules.scripts.models import ScriptFormat


class GenerateScriptRequest(BaseModel):
    title: str
    topic_id: uuid.UUID | None = None
    format: ScriptFormat
    key_points: list[str] = []


class ScriptVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version_number: int
    hook: str | None
    setup: str | None
    promise: str | None
    main_points: str | None
    examples: str | None
    transitions: str | None
    pattern_interrupts: str | None
    cta: str | None
    ending: str | None
    full_text: str | None
    generated_by: str


class ScriptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    format: ScriptFormat
    versions: list[ScriptVersionOut]


class _GeneratedScript(BaseModel):
    hook: str
    setup: str
    promise: str
    main_points: list[str]
    examples: list[str]
    transitions: list[str]
    pattern_interrupts: list[str]
    cta: str
    ending: str
