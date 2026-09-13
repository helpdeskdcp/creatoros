import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.data_quality import Metric
from app.modules.videos.models import VideoFormat


class VideoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    channel_id: uuid.UUID
    youtube_video_id: str
    title: str
    thumbnail_url: str | None
    published_at: datetime | None
    duration_seconds: int | None
    format: VideoFormat | None
    view_count: int | None
    like_count: int | None
    comment_count: int | None


class FormatStats(BaseModel):
    """Real per-format aggregates — never a bare count. `avg_views` and
    `avg_engagement_rate` are None (not zero) when there aren't enough
    videos of this format to trust an average, same discipline as Metric."""

    video_count: int
    total_views: int
    avg_views: float | None
    avg_engagement_rate: float | None
    sample_size_for_averages: int


class ShortsVsLongForm(BaseModel):
    shorts: FormatStats
    long_form: FormatStats


class ChannelIntelligence(BaseModel):
    """The Channel Intelligence dashboard payload. Every field is a Metric
    envelope so the frontend always knows whether a number is REAL,
    ESTIMATED, or INSUFFICIENT_DATA — never a bare guessed number."""

    total_views: Metric
    subscriber_count: Metric
    average_views: Metric
    median_views: Metric
    views_velocity_7d: Metric
    upload_frequency_per_week: Metric
    engagement_rate: Metric
    shorts_vs_long_form: Metric[ShortsVsLongForm]
    top_videos: list[VideoOut]
    weak_videos: list[VideoOut]
