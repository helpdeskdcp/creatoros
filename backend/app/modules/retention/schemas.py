import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RetentionMetricOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    video_id: uuid.UUID
    computed_at: datetime
    early_dropoff_pct: float | None
    mid_video_dropoff_pct: float | None
    ending_dropoff_pct: float | None
    hook_failure_detected: bool | None
    strong_segment_notes: str | None
    data_quality: str
    sample_size: int
    insight: str | None
