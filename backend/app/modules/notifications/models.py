import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class NotificationChannel(str, enum.Enum):
    IN_APP = "in_app"
    EMAIL = "email"
    TELEGRAM = "telegram"


class NotificationEvent(str, enum.Enum):
    NEW_OPPORTUNITY = "new_opportunity"
    PERFORMANCE_ANOMALY = "performance_anomaly"
    COMPETITOR_SPIKE = "competitor_spike"
    SYNC_FAILURE = "sync_failure"
    WEEKLY_REPORT = "weekly_report"
    RECOMMENDATION_READY = "recommendation_ready"
    GROWTH_ACTIONS_READY = "growth_actions_ready"
    PUBLISHING_RESULT = "publishing_result"


class Notification(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event: Mapped[NotificationEvent] = mapped_column(
        Enum(NotificationEvent, name="notification_event"), nullable=False
    )
    channel: Mapped[NotificationChannel] = mapped_column(
        Enum(NotificationChannel, name="notification_channel"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_error: Mapped[str | None] = mapped_column(Text, nullable=True)
