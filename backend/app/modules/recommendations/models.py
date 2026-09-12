import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class Recommendation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Next Best Video output. Scores are kept separate per the Growth OS
    rule: never combine viral/subscriber/retention potential into one
    misleading number."""

    __tablename__ = "recommendations"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("topics.id", ondelete="SET NULL"), nullable=True
    )

    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    topic: Mapped[str] = mapped_column(String(300), nullable=False)
    format: Mapped[str] = mapped_column(String(50), nullable=False)
    target_audience: Mapped[str | None] = mapped_column(String(300), nullable=True)
    content_angle: Mapped[str | None] = mapped_column(Text, nullable=True)
    hook: Mapped[str | None] = mapped_column(Text, nullable=True)
    title_candidates_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumbnail_concept: Mapped[str | None] = mapped_column(Text, nullable=True)

    reason: Mapped[str] = mapped_column(Text, nullable=False)
    supporting_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)

    opportunity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    viral_potential_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    discovery_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    subscriber_potential_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    retention_potential_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    audience_fit_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    confidence: Mapped[str] = mapped_column(String(24), nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
