"""Probability Engine: empirical-baseline predictions, never a black-box
model claiming false precision. A prediction is "what fraction of this
channel's own comparable historical videos reached this threshold by this
horizon" -- deterministic, reproducible, and honestly INSUFFICIENT_DATA
when the channel doesn't have enough comparable history yet.

CreatorOS must never present a prediction as a guarantee -- see
probability/confidence/evidence/sample_size/horizon on every record."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class PredictionMetric(str, enum.Enum):
    VIEWS = "VIEWS"
    SUBSCRIBERS = "SUBSCRIBERS"


class PredictionConfidence(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class PredictionOutcome(str, enum.Enum):
    MET = "MET"
    NOT_MET = "NOT_MET"


class PredictionRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "prediction_records"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    channel_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Nullable: a prediction can be for a hypothetical "next video" (no
    # video yet) or for a specific existing video's future trajectory.
    video_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("videos.id", ondelete="CASCADE"), nullable=True, index=True
    )
    metric: Mapped[PredictionMetric] = mapped_column(
        Enum(PredictionMetric, name="prediction_metric"), nullable=False
    )
    threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)

    # None when confidence is INSUFFICIENT_DATA -- never a fabricated number.
    probability_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[PredictionConfidence] = mapped_column(
        Enum(PredictionConfidence, name="prediction_confidence"), nullable=False
    )
    comparable_video_count: Mapped[int] = mapped_column(Integer, nullable=False)
    positive_factors: Mapped[str | None] = mapped_column(Text, nullable=True)
    negative_factors: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)

    model_version: Mapped[str] = mapped_column(String(32), nullable=False, default="empirical-baseline-v1")
    data_freshness_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Calibration: filled in once the horizon has elapsed and the real
    # outcome is known -- never inferred, only recorded from real data.
    actual_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_outcome: Mapped[PredictionOutcome | None] = mapped_column(
        Enum(PredictionOutcome, name="prediction_outcome"), nullable=True
    )
    outcome_recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
