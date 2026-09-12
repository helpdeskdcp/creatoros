import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class SeoRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "seo_records"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    video_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("videos.id", ondelete="SET NULL"), nullable=True
    )

    title_suggestions: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    keywords: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    chapters: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list of {time,title}
    hashtags: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    search_intent: Mapped[str | None] = mapped_column(String(200), nullable=True)
    topic_clusters: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    generated_by: Mapped[str] = mapped_column(String(32), default="ai", nullable=False)
