"""Channel model: a creator's own connected YouTube channel."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class SyncStatus(str, enum.Enum):
    NEVER_SYNCED = "NEVER_SYNCED"
    PENDING = "PENDING"
    SYNCING = "SYNCING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class Channel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "channels"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    youtube_channel_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumbnail_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    country: Mapped[str | None] = mapped_column(String(8), nullable=True)

    subscriber_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    view_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    video_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # OAuth token material for authorized (non-public) API access. Encrypted
    # at rest via app.core.crypto before being written to these columns.
    oauth_access_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    oauth_refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    oauth_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    sync_status: Mapped[SyncStatus] = mapped_column(
        Enum(SyncStatus, name="channel_sync_status"),
        default=SyncStatus.NEVER_SYNCED,
        nullable=False,
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
