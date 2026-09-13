"""Thumbnail Vision Analysis: deterministic pixel-level metrics computed
from the video's actual live thumbnail image -- never an AI guess, never
a claimed CTR effect (see analysis.py's module docstring)."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class ThumbnailAnalysis(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "thumbnail_analyses"

    video_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    image_url: Mapped[str] = mapped_column(String(1000), nullable=False)

    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    meets_min_resolution: Mapped[bool] = mapped_column(Boolean, nullable=False)
    meets_aspect_ratio: Mapped[bool] = mapped_column(Boolean, nullable=False)
    contrast_score: Mapped[float] = mapped_column(Float, nullable=False)
    brightness_score: Mapped[float] = mapped_column(Float, nullable=False)
    colorfulness_score: Mapped[float] = mapped_column(Float, nullable=False)
    subject_prominence_score: Mapped[float] = mapped_column(Float, nullable=False)

    # JSON-encoded list[str] -- deterministic recommendations, each citing
    # a real measured number (see analysis.generate_recommendations).
    recommendations_json: Mapped[str] = mapped_column(Text, nullable=False)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
