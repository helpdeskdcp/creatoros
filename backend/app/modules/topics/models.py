import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class OpportunityLevel(str, enum.Enum):
    HIGH = "HIGH_OPPORTUNITY"
    MEDIUM = "MEDIUM_OPPORTUNITY"
    LOW = "LOW_OPPORTUNITY"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class Topic(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "topics"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    trend_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("trends.id", ondelete="SET NULL"), nullable=True
    )


class Opportunity(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """The Topic Opportunity Engine's explainable output for one topic."""

    __tablename__ = "opportunities"

    topic_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("topics.id", ondelete="CASCADE"), nullable=False, index=True
    )
    audience_demand_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    momentum_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    competition_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    creator_fit_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    historical_performance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    content_gap_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    freshness_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    level: Mapped[OpportunityLevel] = mapped_column(
        Enum(OpportunityLevel, name="opportunity_level"), nullable=False
    )
    sample_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
