import uuid

from pydantic import BaseModel, ConfigDict

from app.modules.research.models import SourceCredibility


class CreateResearchProjectRequest(BaseModel):
    title: str
    topic_id: uuid.UUID | None = None


class ResearchProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    summary: str | None
    notes: str | None
    topic_id: uuid.UUID | None


class AddSourceRequest(BaseModel):
    url: str
    title: str | None = None
    claim: str | None = None
    citation: str | None = None


class ResearchSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    url: str
    title: str | None
    claim: str | None
    citation: str | None
    credibility: SourceCredibility
    added_by_ai: bool


class VerifySourceRequest(BaseModel):
    credibility: SourceCredibility
