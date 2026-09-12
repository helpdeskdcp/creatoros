import uuid

from pydantic import BaseModel, ConfigDict, Field


class GenerateTitlesRequest(BaseModel):
    topic: str
    topic_id: uuid.UUID | None = None
    video_id: uuid.UUID | None = None
    count: int = Field(default=6, ge=1, le=12)


class TitleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    text: str
    ctr_potential_score: float | None
    clarity_score: float | None
    specificity_score: float | None
    curiosity_score: float | None
    search_relevance_score: float | None
    audience_fit_score: float | None
    generated_by: str


class _GeneratedTitle(BaseModel):
    text: str = Field(max_length=100)
    clarity_score: float = Field(ge=0, le=100)
    specificity_score: float = Field(ge=0, le=100)
    curiosity_score: float = Field(ge=0, le=100)
    search_relevance_score: float = Field(ge=0, le=100)
    audience_fit_score: float = Field(ge=0, le=100)


class GeneratedTitlesResponse(BaseModel):
    titles: list[_GeneratedTitle]
