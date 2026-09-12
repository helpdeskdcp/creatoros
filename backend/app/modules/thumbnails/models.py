import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class ThumbnailBrief(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A generated plan for a thumbnail — not the image itself. Image
    generation, when configured, is invoked via the same AI provider
    abstraction and the resulting asset URL/path is stored in image_path."""

    __tablename__ = "thumbnail_briefs"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    video_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("videos.id", ondelete="SET NULL"), nullable=True
    )
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("topics.id", ondelete="SET NULL"), nullable=True
    )

    subject: Mapped[str] = mapped_column(Text, nullable=False)
    emotion: Mapped[str | None] = mapped_column(String(100), nullable=True)
    text_overlay: Mapped[str | None] = mapped_column(String(60), nullable=True)
    text_overlay_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    visual_hierarchy_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    contrast_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    curiosity_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    brand_consistency_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    image_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
