import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.modules.predictions.models import PredictionConfidence, PredictionMetric, PredictionOutcome


class PredictVideoThresholdRequest(BaseModel):
    threshold: int = Field(gt=0)
    horizon_days: int = Field(gt=0, le=365)


class PredictSubscriberThresholdRequest(BaseModel):
    threshold: int = Field(gt=0)
    horizon_days: int = Field(gt=0, le=365)


class PredictionRecordOut(BaseModel):
    id: uuid.UUID
    channel_id: uuid.UUID
    video_id: uuid.UUID | None
    metric: PredictionMetric
    threshold: int
    horizon_days: int
    probability_percent: int | None
    confidence: PredictionConfidence
    comparable_video_count: int
    positive_factors: str | None
    negative_factors: str | None
    evidence: str
    model_version: str
    data_freshness_at: datetime | None
    actual_value: int | None
    actual_outcome: PredictionOutcome | None
    outcome_recorded_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class RecordOutcomeRequest(BaseModel):
    actual_value: int = Field(ge=0)


class CalibrationBucketOut(BaseModel):
    probability_range: str
    predicted_rate: float
    actual_rate: float
    count: int
