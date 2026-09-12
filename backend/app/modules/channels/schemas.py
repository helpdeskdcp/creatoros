import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.channels.models import SyncStatus


class ChannelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    youtube_channel_id: str
    title: str
    description: str | None
    thumbnail_url: str | None
    country: str | None
    subscriber_count: int | None
    view_count: int | None
    video_count: int | None
    sync_status: SyncStatus
    last_synced_at: datetime | None
    last_sync_error: str | None


class ConnectChannelRequest(BaseModel):
    """Connect without OAuth, using only the public channel id (read-only
    mode — no authorized analytics/publishing until OAuth is completed)."""

    youtube_channel_id: str


class OAuthAuthorizeResponse(BaseModel):
    authorize_url: str
    state: str


class OAuthCallbackRequest(BaseModel):
    code: str
    state: str
