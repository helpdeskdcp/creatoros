import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.video_generation.models import AIVideoJobStatus, VideoGenerationType, VideoPriorityMode


class CreateVideoJobRequest(BaseModel):
    generation_type: VideoGenerationType
    prompt: str | None = Field(default=None, max_length=4000)
    priority_mode: VideoPriorityMode = VideoPriorityMode.AUTO
    duration: int | None = Field(default=None, ge=1, le=60)
    resolution: str | None = None
    aspect_ratio: str | None = None
    audio: bool = False
    # Image URLs for IMAGE_TO_VIDEO/REFERENCE_TO_VIDEO (any length), or
    # for frame-controlled types: [first_frame_url] / [last_frame_url] /
    # [first_frame_url, last_frame_url].
    input_image_urls: list[str] | None = None
    allow_degraded_config: bool = True


class DegradationNoteOut(BaseModel):
    notes: list[str]


class VideoJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    generation_type: VideoGenerationType
    priority_mode: VideoPriorityMode
    status: AIVideoJobStatus
    attempt: int
    max_attempts: int
    fallback_used: bool
    degraded_from_request: bool
    primary_model_id: str | None
    selected_model_id: str | None
    resolution: str | None
    aspect_ratio: str | None
    duration_seconds: int | None
    cost_estimate: float | None
    cost_actual: float | None
    latency_ms: int | None
    error: str | None
    created_at: datetime
    submitted_at: datetime | None
    completed_at: datetime | None


class VideoModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    model_id: str
    name: str
    provider: str
    is_free: bool
    is_active: bool
    supports_audio: bool
    quality_tier_score: float
    circuit_state: str
    last_checked_at: datetime
