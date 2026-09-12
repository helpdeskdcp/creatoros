import uuid

from sqlalchemy import Boolean, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class Title(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "titles"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("topics.id", ondelete="SET NULL"), nullable=True
    )
    video_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("videos.id", ondelete="SET NULL"), nullable=True
    )
    text: Mapped[str] = mapped_column(String(200), nullable=False)

    ctr_potential_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    clarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    specificity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    curiosity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    search_relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    audience_fit_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    is_experiment_variant: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    generated_by: Mapped[str] = mapped_column(String(32), default="ai", nullable=False)
