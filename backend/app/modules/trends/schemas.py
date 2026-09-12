import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.trends.models import TrendSource


class TrendOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    keyword: str
    source: TrendSource
    trend_score: float | None
    growth_score: float | None
    competition_score: float | None
    audience_fit_score: float | None
    creator_fit_score: float | None
    timeliness_score: float | None
    content_gap_score: float | None
    opportunity_score: float | None
    sample_size: int
    explanation: str | None
    detected_at: datetime
