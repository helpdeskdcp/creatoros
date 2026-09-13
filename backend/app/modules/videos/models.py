"""Video and per-snapshot video_metrics models."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class VideoFormat(str, enum.Enum):
    SHORT = "SHORT"
    LONG_FORM = "LONG_FORM"


class Video(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "videos"

    channel_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    youtube_video_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    format: Mapped[VideoFormat | None] = mapped_column(
        Enum(VideoFormat, name="video_format"), nullable=True
    )
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)  # comma-separated

    # Latest known counters, denormalized for fast listing/sorting.
    view_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    like_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    comment_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class VideoMetricSnapshot(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A point-in-time snapshot of a video's public/authorized metrics.

    Storing snapshots (rather than overwriting Video's counters) is what lets
    the retention/outcome-learning engines compute velocity and early vs.
    lifetime performance instead of only ever seeing "now".
    """

    __tablename__ = "video_metrics"

    video_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    view_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    like_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    comment_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Only populated when the channel has authorized YouTube Analytics access.
    average_view_duration_seconds: Mapped[float | None] = mapped_column(nullable=True)
    average_view_percentage: Mapped[float | None] = mapped_column(nullable=True)
    estimated_ctr: Mapped[float | None] = mapped_column(nullable=True)
    subscribers_gained: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Views during the Analytics-report window this subscribers_gained figure
    # covers -- deliberately NOT the same as view_count above, which is the
    # Data API's cumulative-lifetime total used by videos/service.py's 7-day
    # velocity calculation. Conflating the two would silently corrupt that
    # calculation (a small daily figure diffed against a large cumulative
    # one). subscriber_conversion_rate divides by this field, never by
    # view_count.
    window_view_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    traffic_source_breakdown_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    source: Mapped[str] = mapped_column(String(32), default="youtube_data_api", nullable=False)
