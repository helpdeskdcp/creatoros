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


class OAuthStatusResponse(BaseModel):
    """Server-side OAuth diagnostics — never includes the client secret or
    any token. `publishing_status` is an operator-declared value (see
    Settings.youtube_oauth_publishing_status): CreatorOS cannot query
    Google's own consent-screen state, so this reflects what the
    administrator configured, not something auto-detected."""

    configured: bool
    publishing_status: str
    redirect_uri: str
    scopes: list[str]
