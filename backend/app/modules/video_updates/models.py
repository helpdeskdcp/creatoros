"""Verified Update Engine: proposals to change an EXISTING published
video's metadata on YouTube, approval-gated, with a read-back verification
step that decides SUCCEEDED_VERIFIED vs FAILED_NOT_VERIFIED -- a local DB
write is never treated as proof YouTube actually changed."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class VideoUpdateField(str, enum.Enum):
    TITLE = "TITLE"
    DESCRIPTION = "DESCRIPTION"
    TAGS = "TAGS"


class VideoUpdateStatus(str, enum.Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    REJECTED = "REJECTED"
    EXECUTING = "EXECUTING"
    SUCCEEDED_VERIFIED = "SUCCEEDED_VERIFIED"
    FAILED_NOT_VERIFIED = "FAILED_NOT_VERIFIED"


class VideoUpdateImpact(str, enum.Enum):
    """Classifies a change's REAL measured effect -- view VELOCITY
    (views/day) before vs. after the change, never the immediate raw view
    count (which only ever goes up and would make every change look like
    a "win"). Never claims causation from correlation: this is a
    correlational before/after comparison on one channel, not a
    controlled experiment."""

    WIN = "WIN"
    NEUTRAL = "NEUTRAL"
    LOSS = "LOSS"
    INCONCLUSIVE = "INCONCLUSIVE"


class VideoUpdateProposal(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "video_update_proposals"

    video_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Denormalized from video->channel->owner for a single-column ownership/
    # isolation filter (matches MediaAsset/PublishingRun's own convention).
    owner_user_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    field: Mapped[VideoUpdateField] = mapped_column(
        Enum(VideoUpdateField, name="video_update_field"), nullable=False
    )
    # TAGS stored as a JSON array string; TITLE/DESCRIPTION as raw text.
    # previous_value is a DISPLAY estimate captured at proposal time (from
    # our last-synced local copy) -- the AUTHORITATIVE previous value used
    # for the actual merge/rollback is re-fetched live from YouTube at
    # execution time and stored in verified_previous_value.
    previous_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_previous_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_value: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[VideoUpdateStatus] = mapped_column(
        Enum(VideoUpdateStatus, name="video_update_status"),
        nullable=False, default=VideoUpdateStatus.PENDING_APPROVAL,
    )
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Self-referential: set when this proposal exists specifically to
    # revert an earlier one. Rollback is itself a normal PENDING_APPROVAL
    # proposal -- reverting a live write is still a live write.
    rollback_of_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("video_update_proposals.id", ondelete="SET NULL"), nullable=True
    )

    # --- Performance measurement / learning loop (only meaningful once
    # status == SUCCEEDED_VERIFIED) ---
    observation_window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=14)
    baseline_view_velocity: Mapped[float | None] = mapped_column(Float, nullable=True)
    post_view_velocity: Mapped[float | None] = mapped_column(Float, nullable=True)
    impact_outcome: Mapped[VideoUpdateImpact | None] = mapped_column(
        Enum(VideoUpdateImpact, name="video_update_impact"), nullable=True
    )
    impact_measured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
