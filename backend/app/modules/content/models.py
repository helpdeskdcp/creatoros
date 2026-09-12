import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class ContentStatus(str, enum.Enum):
    IDEA = "IDEA"
    RESEARCH = "RESEARCH"
    OUTLINE = "OUTLINE"
    SCRIPT = "SCRIPT"
    RECORDING = "RECORDING"
    EDITING = "EDITING"
    THUMBNAIL = "THUMBNAIL"
    SEO = "SEO"
    READY = "READY"
    PUBLISHED = "PUBLISHED"
    ANALYZING = "ANALYZING"


class ContentItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A single Kanban card carrying a piece of content through the pipeline.
    Scheduling fields double as the content calendar (queried by due_at)."""

    __tablename__ = "content_items"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    topic_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("topics.id", ondelete="SET NULL"), nullable=True
    )
    video_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("videos.id", ondelete="SET NULL"), nullable=True
    )

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[ContentStatus] = mapped_column(
        Enum(ContentStatus, name="content_status"), default=ContentStatus.IDEA, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    checklist_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_publish_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    is_short: Mapped[bool] = mapped_column(default=False, nullable=False)
    recurring_format: Mapped[str | None] = mapped_column(String(100), nullable=True)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("distribution_campaigns.id", ondelete="SET NULL"), nullable=True
    )

    events: Mapped[list["ContentEvent"]] = relationship(
        back_populates="content_item", cascade="all, delete-orphan", order_by="ContentEvent.created_at"
    )


class ContentEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Append-only status/comment history for a content item."""

    __tablename__ = "content_events"

    content_item_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)  # status_change | comment
    from_status: Mapped[ContentStatus | None] = mapped_column(
        Enum(ContentStatus, name="content_status"), nullable=True
    )
    to_status: Mapped[ContentStatus | None] = mapped_column(
        Enum(ContentStatus, name="content_status"), nullable=True
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    content_item: Mapped["ContentItem"] = relationship(back_populates="events")
