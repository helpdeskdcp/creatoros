import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.experiments.models import ExperimentStatus


class CreateExperimentRequest(BaseModel):
    experiment_type: str
    hypothesis: str
    metric: str
    video_id: uuid.UUID | None = None
    minimum_sample_size: int = 30
    variants: list[str]  # first is control


class VariantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    content: str
    sample_size: int
    metric_value: float | None


class ExperimentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    experiment_type: str
    hypothesis: str
    metric: str
    status: ExperimentStatus
    started_at: datetime | None
    ended_at: datetime | None
    minimum_sample_size: int
    confidence: str | None
    variants: list[VariantOut]


class RecordVariantResultRequest(BaseModel):
    sample_size: int
    metric_value: float
