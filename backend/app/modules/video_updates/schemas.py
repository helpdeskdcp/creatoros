import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.modules.video_updates.models import VideoUpdateField, VideoUpdateImpact, VideoUpdateStatus


class ProposeVideoUpdateRequest(BaseModel):
    video_id: uuid.UUID
    field: VideoUpdateField
    proposed_value: Any
    reason: str = Field(min_length=1, max_length=2000)
    evidence: str | None = Field(default=None, max_length=4000)


class VideoUpdateProposalOut(BaseModel):
    id: uuid.UUID
    video_id: uuid.UUID
    field: VideoUpdateField
    previous_value: str | None
    verified_previous_value: str | None
    proposed_value: str
    reason: str
    evidence: str | None
    status: VideoUpdateStatus
    approved_at: datetime | None
    executed_at: datetime | None
    verified_at: datetime | None
    error_message: str | None
    rollback_of_id: uuid.UUID | None
    observation_window_days: int
    baseline_view_velocity: float | None
    post_view_velocity: float | None
    impact_outcome: VideoUpdateImpact | None
    impact_measured_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}
