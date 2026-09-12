import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class RetentionMetric(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Per-video retention analysis, computed only from authorized YouTube
    Analytics data (average_view_percentage / video_metrics snapshots)."""

    __tablename__ = "retention_metrics"

    video_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    early_dropoff_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    mid_video_dropoff_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    ending_dropoff_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    hook_failure_detected: Mapped[bool | None] = mapped_column(nullable=True)
    strong_segment_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    data_quality: Mapped[str] = mapped_column(String(24), nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    insight: Mapped[str | None] = mapped_column(Text, nullable=True)
