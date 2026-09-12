import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class ExperimentStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class Experiment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A/B experiments for titles/thumbnails/hooks/CTA/format/publish-time —
    one generic model, not a separate table per experiment type."""

    __tablename__ = "experiments"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    video_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("videos.id", ondelete="SET NULL"), nullable=True
    )
    # title|thumbnail|hook|cta|format|publish_window
    experiment_type: Mapped[str] = mapped_column(String(50), nullable=False)
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    metric: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g. "ctr", "avg_view_duration"
    status: Mapped[ExperimentStatus] = mapped_column(
        Enum(ExperimentStatus, name="experiment_status"), default=ExperimentStatus.DRAFT, nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    minimum_sample_size: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    winning_variant_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey(
            "experiment_variants.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_experiments_winning_variant_id",
        ),
        nullable=True,
    )
    confidence: Mapped[str | None] = mapped_column(String(24), nullable=True)

    variants: Mapped[list["ExperimentVariant"]] = relationship(
        back_populates="experiment",
        cascade="all, delete-orphan",
        foreign_keys="ExperimentVariant.experiment_id",
    )


class ExperimentVariant(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "experiment_variants"

    experiment_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(50), nullable=False)  # "control" | "variant_a" | ...
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metric_value: Mapped[float | None] = mapped_column(nullable=True)

    experiment: Mapped["Experiment"] = relationship(
        back_populates="variants", foreign_keys=[experiment_id]
    )
