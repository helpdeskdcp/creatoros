import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class TrendSource(str, enum.Enum):
    YOUTUBE_SIGNAL = "YOUTUBE_SIGNAL"
    CREATOR_HISTORY = "CREATOR_HISTORY"
    COMPETITOR_MOMENTUM = "COMPETITOR_MOMENTUM"
    GOOGLE_TRENDS = "GOOGLE_TRENDS"
    RSS_NEWS = "RSS_NEWS"


class Trend(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A detected topic signal, scored explainably (never a bare number)."""

    __tablename__ = "trends"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    keyword: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    source: Mapped[TrendSource] = mapped_column(Enum(TrendSource, name="trend_source"), nullable=False)

    trend_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    growth_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    competition_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    audience_fit_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    creator_fit_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    timeliness_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    content_gap_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    opportunity_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    sample_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
