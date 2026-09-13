import uuid
from datetime import datetime

from pydantic import BaseModel

from app.core.data_quality import Metric


class SnapshotOut(BaseModel):
    id: uuid.UUID
    channel_id: uuid.UUID
    captured_at: datetime
    total_views: int | None
    total_subscribers: int | None
    average_views_per_video: float | None
    median_views_per_video: float | None
    upload_frequency_per_week: float | None
    engagement_rate: float | None
    performance_score: float | None
    engagement_score: float | None
    data_quality: str
    sample_size: int

    model_config = {"from_attributes": True}


class GrowthScorecardOut(BaseModel):
    channel_id: uuid.UUID
    computed_at: datetime
    content_score: Metric
    discovery_score: Metric
    ctr_score: Metric
    retention_score: Metric
    subscriber_conversion_score: Metric
    returning_viewers_score: Metric
    distribution_score: Metric
    consistency_score: Metric
    explanation: str


class GrowthBottleneck(BaseModel):
    bottleneck: str
    evidence: str
    affected_videos: list[str]
    affected_metrics: list[str]
    recommended_action: str
    confidence: str
    sample_size: int


class GrowthDiagnosisOut(BaseModel):
    channel_id: uuid.UUID
    computed_at: datetime
    bottlenecks: list[GrowthBottleneck]
    note: str | None = None


class SubscriberGrowthOut(BaseModel):
    channel_id: uuid.UUID
    dimension: str
    subscriber_growth_rate: Metric
    subscriber_conversion_rate: Metric
    subscribers_per_1000_views: Metric
    returning_viewer_rate: Metric


class GrowthActionOut(BaseModel):
    id: uuid.UUID
    channel_id: uuid.UUID | None
    run_date: datetime
    priority: int
    action_type: str
    title: str
    reason: str
    evidence: str | None
    expected_objective: str | None
    confidence: str
    requires_approval: bool
    execution_status: str

    model_config = {"from_attributes": True}
