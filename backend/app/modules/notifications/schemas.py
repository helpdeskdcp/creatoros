import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.notifications.models import NotificationChannel, NotificationEvent


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event: NotificationEvent
    channel: NotificationChannel
    title: str
    body: str
    is_read: bool
    sent_at: datetime | None
    delivery_error: str | None
