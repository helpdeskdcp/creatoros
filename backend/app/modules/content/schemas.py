import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.content.models import ContentStatus


class CreateContentItemRequest(BaseModel):
    title: str
    topic_id: uuid.UUID | None = None
    due_at: datetime | None = None
    scheduled_publish_at: datetime | None = None
    timezone: str = "UTC"
    is_short: bool = False
    notes: str | None = None


class UpdateContentStatusRequest(BaseModel):
    status: ContentStatus
    comment: str | None = None


class ContentEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: str
    from_status: ContentStatus | None
    to_status: ContentStatus | None
    comment: str | None
    created_at: datetime


class ContentItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    status: ContentStatus
    topic_id: uuid.UUID | None
    video_id: uuid.UUID | None
    due_at: datetime | None
    scheduled_publish_at: datetime | None
    timezone: str
    is_short: bool
    notes: str | None
