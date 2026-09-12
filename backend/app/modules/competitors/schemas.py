import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CompetitorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    youtube_channel_id: str
    title: str
    thumbnail_url: str | None
    subscriber_count: int | None
    view_count: int | None
    video_count: int | None
    last_synced_at: datetime | None
    notes: str | None


class AddCompetitorRequest(BaseModel):
    youtube_channel_id: str
    notes: str | None = None


class CompetitorVideoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    youtube_video_id: str
    title: str
    thumbnail_url: str | None
    published_at: datetime | None
    view_count: int | None
    like_count: int | None
    comment_count: int | None


class ContentGap(BaseModel):
    """One detected opportunity from the Competitor Opportunity Engine."""

    keyword: str
    competitor_count: int
    total_competitor_views: int
    creator_has_covered: bool
    signal: str
