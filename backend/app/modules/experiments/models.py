import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
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
    # The real published video this variant's performance is measured
    # from. When set, measure_variant() pulls the real metric straight
    # from VideoMetricSnapshot/Video instead of requiring a human to
    # manually type in a number they read somewhere else.
    video_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("videos.id", ondelete="SET NULL"), nullable=True
    )
    measured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    experiment: Mapped["Experiment"] = relationship(
        back_populates="variants", foreign_keys=[experiment_id]
    )


class CreatorLearningSignal(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """The creator-specific learning loop's persistent state: real
    win/loss counts per signal, built ONLY from concluded experiments
    (real historical performance, per _maybe_conclude) -- never from an
    LLM's self-reported guess. One row per (owner, signal_type,
    signal_key); wins/losses accumulate across every experiment that
    ever touched this signal, so the profile gets more confident over
    time instead of resetting per experiment.
    """

    __tablename__ = "creator_learning_signals"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "signal_type", "signal_key", name="uq_learning_signal"),
    )

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # topic_keyword | title_keyword | hook_keyword | format | publish_window
    signal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    signal_key: Mapped[str] = mapped_column(String(200), nullable=False)
    wins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    losses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
