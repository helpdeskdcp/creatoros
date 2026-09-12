"""Growth OS: multi-platform distribution. Extends the content workspace's
Kanban model rather than duplicating it — a DistributionCampaign groups
ContentItems, and each DistributionAsset is one platform-specific derivative
of a source video (never a duplicate copy of the raw media itself)."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class CampaignStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    READY = "READY"
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ANALYZING = "ANALYZING"


class Platform(str, enum.Enum):
    YOUTUBE = "YOUTUBE"
    INSTAGRAM = "INSTAGRAM"
    FACEBOOK = "FACEBOOK"
    X = "X"
    LINKEDIN = "LINKEDIN"


class AssetStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    READY = "READY"
    SCHEDULED = "SCHEDULED"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


class DistributionCampaign(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "distribution_campaigns"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_video_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("videos.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[CampaignStatus] = mapped_column(
        Enum(CampaignStatus, name="campaign_status"), default=CampaignStatus.DRAFT, nullable=False
    )
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DistributionAsset(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One platform-specific derivative (never the raw media file itself —
    see docs/operations.md VPS Storage Optimization)."""

    __tablename__ = "distribution_assets"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("distribution_campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_video_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("videos.id", ondelete="SET NULL"), nullable=True
    )
    source_segment: Mapped[str | None] = mapped_column(String(200), nullable=True)  # e.g. "00:42-01:10"
    platform: Mapped[Platform] = mapped_column(Enum(Platform, name="distribution_platform"), nullable=False)
    format: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g. "reel", "post", "thread"

    hook: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    cta: Mapped[str | None] = mapped_column(Text, nullable=True)
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)

    status: Mapped[AssetStatus] = mapped_column(
        Enum(AssetStatus, name="distribution_asset_status"), default=AssetStatus.DRAFT, nullable=False
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    platform_post_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    publication_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
