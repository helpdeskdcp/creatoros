import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.topics.models import OpportunityLevel


class CreateTopicRequest(BaseModel):
    title: str
    description: str | None = None
    trend_id: uuid.UUID | None = None


class TopicOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    trend_id: uuid.UUID | None


class OpportunityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    topic_id: uuid.UUID
    audience_demand_score: float | None
    momentum_score: float | None
    competition_score: float | None
    creator_fit_score: float | None
    historical_performance_score: float | None
    content_gap_score: float | None
    freshness_score: float | None
    level: OpportunityLevel
    sample_size: int
    explanation: str
    computed_at: datetime
