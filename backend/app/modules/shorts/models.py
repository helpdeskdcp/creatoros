"""Long video -> Shorts/Reels content factory. Every stage's real output
is persisted before the next stage starts (not just a final result) --
this is what makes a job resumable: a retried task can check what's
already been computed and skip straight to the next incomplete stage
instead of redoing expensive work (or, worse, silently redoing it and
producing duplicate candidates)."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class VideoJobStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    VALIDATING = "VALIDATING"
    EXTRACTING_AUDIO = "EXTRACTING_AUDIO"
    TRANSCRIBING = "TRANSCRIBING"
    DETECTING_MOMENTS = "DETECTING_MOMENTS"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"  # candidates scored, awaiting creator approval to render
    RENDERING = "RENDERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class VideoProcessingJob(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "video_processing_jobs"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_media_asset_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    status: Mapped[VideoJobStatus] = mapped_column(
        Enum(VideoJobStatus, name="video_job_status"), default=VideoJobStatus.QUEUED, nullable=False, index=True
    )
    progress_pct: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)


class Transcript(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "transcripts"

    job_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("video_processing_jobs.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    full_text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)


class TranscriptSegment(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "transcript_segments"

    transcript_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    start_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    end_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)


class ShortCandidateStatus(str, enum.Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RENDERING = "RENDERING"
    RENDERED = "RENDERED"
    RENDER_FAILED = "RENDER_FAILED"


class ShortCandidate(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One ranked candidate moment. Never a random 30s window -- score and
    score_breakdown_json exist specifically so a creator (or an
    engineer debugging bad picks) can see WHY this window was ranked
    where it was, not just that it was."""

    __tablename__ = "short_candidates"

    job_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("video_processing_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    start_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    end_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    score_breakdown_json: Mapped[str] = mapped_column(Text, nullable=False)
    transcript_excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ShortCandidateStatus] = mapped_column(
        Enum(ShortCandidateStatus, name="short_candidate_status"),
        default=ShortCandidateStatus.PENDING_APPROVAL, nullable=False,
    )
    generated_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    generated_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_hook: Mapped[str | None] = mapped_column(Text, nullable=True)
    rendered_media_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True
    )
    render_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    rendered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
