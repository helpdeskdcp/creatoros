"""Channel/video analytics + Growth OS subscriber-growth extensions.

Growth OS additions (subscriber_growth_metrics, growth_scores, growth_actions)
live here because they are computed FROM analytics_snapshots/video_metrics —
this is an extension of the analytics engine, not a parallel system.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class AnalyticsSnapshot(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A point-in-time rollup of a channel's health, computed from real
    stored video_metrics — never a fabricated number."""

    __tablename__ = "analytics_snapshots"

    channel_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    total_views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_subscribers: Mapped[int | None] = mapped_column(Integer, nullable=True)
    average_views_per_video: Mapped[float | None] = mapped_column(Float, nullable=True)
    median_views_per_video: Mapped[float | None] = mapped_column(Float, nullable=True)
    upload_frequency_per_week: Mapped[float | None] = mapped_column(Float, nullable=True)
    engagement_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    performance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    engagement_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    retention_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    subscriber_conversion_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    data_quality: Mapped[str] = mapped_column(String(24), nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class SubscriberGrowthMetric(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Growth OS: subscriber acquisition efficiency, broken down by the
    dimensions the spec requires (topic/format/source/video/campaign)."""

    __tablename__ = "subscriber_growth_metrics"

    channel_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    dimension: Mapped[str] = mapped_column(String(32), nullable=False)  # overall|topic|format|source|video|campaign
    dimension_key: Mapped[str | None] = mapped_column(String(200), nullable=True)

    subscriber_growth_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    subscriber_conversion_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    subscribers_per_1000_views: Mapped[float | None] = mapped_column(Float, nullable=True)
    returning_viewer_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    data_quality: Mapped[str] = mapped_column(String(24), nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class GrowthScore(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """The Growth Scorecard: component scores shown separately, never merged
    into one misleading number."""

    __tablename__ = "growth_scores"

    channel_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    content_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    discovery_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ctr_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    retention_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    subscriber_conversion_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    returning_viewers_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    distribution_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    consistency_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    sample_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)


class GrowthAction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One item from the Daily AI Growth Agent's 'Today's Top 5 Growth
    Actions'. requires_approval gates execution — the agent never acts
    outside a creator's explicit publishing rules."""

    __tablename__ = "growth_actions"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("channels.id", ondelete="SET NULL"), nullable=True
    )
    run_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_objective: Mapped[str | None] = mapped_column(String(200), nullable=True)
    confidence: Mapped[str] = mapped_column(String(24), nullable=False)
    requires_approval: Mapped[bool] = mapped_column(default=True, nullable=False)
    execution_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
