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
    error_code: str | None
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
    known_zdr_blocked: bool
    success_count: int
    failure_count: int
    last_checked_at: datetime


class VideoGenerationAttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    attempt_number: int
    model_id: str
    outcome: str
    error_code: str | None
    error: str | None
    latency_ms: int | None
    started_at: datetime
    finished_at: datetime | None


class VideoJobRoutingOut(BaseModel):
    """Section 6's routing visibility: what the router decided and why,
    without ever exposing raw provider secrets/internals."""

    routing_mode: VideoPriorityMode
    primary_model_id: str | None
    remaining_fallback_chain: list[str]
    selected_model_id: str | None
    current_attempt: int
    max_attempts: int
    fallback_used: bool
    degraded_from_request: bool
    degradation_notes: list[str]


class CircuitBreakerSummaryOut(BaseModel):
    closed: int
    open: int
    half_open: int


class VideoHealthOut(BaseModel):
    total_models: int
    active_models: int
    inactive_models: int
    free_models: int
    zdr_blocked_models: int
    circuit_breakers: CircuitBreakerSummaryOut


class VideoCapabilitiesOut(BaseModel):
    """Aggregated across the whole active catalog -- "what's possible right
    now, with at least one live model", for a frontend to build its own
    request form without hard-coding a list that will drift from reality."""

    resolutions: list[str]
    aspect_ratios: list[str]
    durations: list[int]
    generation_types: list[str]
    audio_capable_model_count: int
