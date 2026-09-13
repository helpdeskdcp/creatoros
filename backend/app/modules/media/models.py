"""Media asset metadata. The actual bytes live in whatever StorageBackend
is configured (local disk or S3) -- never in this table. See
docs/ and app/core/storage.py."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin
from app.db.types import GUID


class MediaPurpose(str, enum.Enum):
    VIDEO = "VIDEO"
    THUMBNAIL = "THUMBNAIL"


class MediaAsset(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "media_assets"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purpose: Mapped[MediaPurpose] = mapped_column(Enum(MediaPurpose, name="media_purpose"), nullable=False)
    storage_backend: Mapped[str] = mapped_column(String(16), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
