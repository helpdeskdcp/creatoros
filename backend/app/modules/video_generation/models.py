"""User-facing video generation job ledger. Mirrors app.modules.publishing's
PublishingRun/PublishingAttempt split: VideoJob is the one row per request a
user/UI polls; VideoGenerationAttempt is one row per model-level try within
that job's retry/fallback chain (never a JSON blob -- see its docstring)."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class VideoGenerationType(str, enum.Enum):
    TEXT_TO_VIDEO = "TEXT_TO_VIDEO"
    IMAGE_TO_VIDEO = "IMAGE_TO_VIDEO"
    REFERENCE_TO_VIDEO = "REFERENCE_TO_VIDEO"
    FIRST_FRAME = "FIRST_FRAME"
    LAST_FRAME = "LAST_FRAME"
    FIRST_LAST_FRAME = "FIRST_LAST_FRAME"


class VideoPriorityMode(str, enum.Enum):
    QUALITY = "QUALITY"
    BALANCED = "BALANCED"
    FAST = "FAST"
    LOW_COST = "LOW_COST"
    FREE_FIRST = "FREE_FIRST"
    AUTO = "AUTO"


class AIVideoJobStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    SUBMITTED = "SUBMITTED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class VideoJob(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One user-requested video generation, end to end. `fallback_chain_json`
    and `validated_params_json` are frozen at submission time by
    VideoModelRouter.select_best_model -- what actually got requested, not
    just what the user asked for (closest-valid-configuration resolution
    may have adjusted resolution/duration/audio)."""

    __tablename__ = "video_jobs"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    generation_type: Mapped[VideoGenerationType] = mapped_column(
        Enum(VideoGenerationType, name="video_generation_type"), nullable=False
    )
    priority_mode: Mapped[VideoPriorityMode] = mapped_column(
        Enum(VideoPriorityMode, name="video_priority_mode"), default=VideoPriorityMode.AUTO, nullable=False
    )
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_params_json: Mapped[str] = mapped_column(Text, nullable=False)
    validated_params_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_references_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    degraded_from_request: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    degradation_notes_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    primary_model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    fallback_chain_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    selected_model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_job_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    status: Mapped[AIVideoJobStatus] = mapped_column(
        Enum(AIVideoJobStatus, name="ai_video_job_status"), default=AIVideoJobStatus.QUEUED, nullable=False, index=True
    )
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    # Exponential-backoff-with-jitter gate for the fallback/retry poller --
    # a job due for its next attempt has this <= now(); NULL means
    # "act immediately" (used right after creation).
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    output_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(16), nullable=True)
    aspect_ratio: Mapped[str | None] = mapped_column(String(16), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    cost_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_actual: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VideoGenerationAttempt(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One model-level attempt within a VideoJob's retry/fallback chain.
    Separate table (not a JSON blob on VideoJob) so every attempt is a real,
    queryable row -- required for per-model health/circuit-breaker
    accounting and for "every attempt must be logged" to mean something
    more than a debug string."""

    __tablename__ = "video_generation_attempts"

    video_job_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("video_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)  # submitted|succeeded|failed|timeout
    provider_job_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
