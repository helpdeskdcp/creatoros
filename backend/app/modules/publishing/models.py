"""Growth OS publishing safety layer: rules a creator explicitly sets, and an
idempotent run/attempt ledger for every automated publish action. Extends
the existing Channel/Video/YouTubeProvider — this is not a second YouTube
integration, only the authorization + state-machine wrapper around it."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class PublishingMode(str, enum.Enum):
    ASSIST = "ASSIST"
    AUTO_PREPARE = "AUTO_PREPARE"
    AUTHORIZED_AUTONOMOUS = "AUTHORIZED_AUTONOMOUS"


class PublishingState(str, enum.Enum):
    DRAFT = "DRAFT"
    READY = "READY"
    VALIDATING = "VALIDATING"
    UPLOAD_QUEUED = "UPLOAD_QUEUED"
    UPLOADING = "UPLOADING"
    PROCESSING = "PROCESSING"
    SCHEDULED = "SCHEDULED"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    RETRY_PENDING = "RETRY_PENDING"
    CANCELLED = "CANCELLED"


class PublishingRule(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A creator-defined authorization boundary. AUTHORIZED_AUTONOMOUS actions
    are refused (BLOCK_ACTION) whenever they'd fall outside this row."""

    __tablename__ = "publishing_rules"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mode: Mapped[PublishingMode] = mapped_column(
        Enum(PublishingMode, name="publishing_mode"), default=PublishingMode.ASSIST, nullable=False
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_videos_per_day: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    allowed_categories_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    minimum_content_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    minimum_subscriber_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    allowed_publish_windows_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    allowed_platforms_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    require_thumbnail: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    require_metadata_validation: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PublishingRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One requested publish action, idempotent on idempotency_key so retries
    from Celery never create a duplicate upload."""

    __tablename__ = "publishing_runs"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content_item_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("content_items.id", ondelete="SET NULL"), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    mode: Mapped[PublishingMode] = mapped_column(Enum(PublishingMode, name="publishing_mode"), nullable=False)
    state: Mapped[PublishingState] = mapped_column(
        Enum(PublishingState, name="publishing_state"), default=PublishingState.DRAFT, nullable=False
    )
    youtube_video_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # References an uploaded, ownership-checked MediaAsset -- deliberately
    # NOT a raw client-suppliable filesystem path, which would let a
    # caller ask CreatorOS to "upload" an arbitrary server file to
    # YouTube. execute_run() re-verifies ownership again at execution
    # time regardless (defense in depth).
    video_media_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True
    )
    published_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PublishingAttempt(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One safety-gate evaluation + execution attempt for a PublishingRun."""

    __tablename__ = "publishing_attempts"

    publishing_run_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("publishing_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    gate_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    gate_checks_json: Mapped[str] = mapped_column(Text, nullable=False)
    result: Mapped[str] = mapped_column(String(32), nullable=False)  # blocked | succeeded | failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
