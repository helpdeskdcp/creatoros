"""YouTubeProvider: the single interface all YouTube data access goes through.

Nothing outside this package should import googleapiclient/httpx directly for
YouTube data. Swapping the real API for a mock (tests) or a future provider
(e.g. a caching proxy) never requires touching channels/videos business logic.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class OAuthTokens:
    access_token: str
    refresh_token: str | None
    expires_at: datetime


@dataclass
class ChannelData:
    youtube_channel_id: str
    title: str
    description: str | None
    thumbnail_url: str | None
    country: str | None
    subscriber_count: int | None
    view_count: int | None
    video_count: int | None


@dataclass
class VideoData:
    youtube_video_id: str
    title: str
    description: str | None
    thumbnail_url: str | None
    published_at: datetime | None
    duration_seconds: int | None
    category_id: str | None
    tags: list[str] = field(default_factory=list)
    view_count: int | None = None
    like_count: int | None = None
    comment_count: int | None = None
    is_short: bool = False


@dataclass
class VideosPage:
    videos: list[VideoData]
    next_page_token: str | None


@dataclass
class AnalyticsRow:
    video_youtube_id: str
    date: datetime
    views: int | None
    average_view_duration_seconds: float | None
    average_view_percentage: float | None
    estimated_ctr: float | None
    subscribers_gained: int | None


@dataclass
class UploadMetadata:
    title: str
    description: str
    tags: list[str]
    category_id: str
    privacy_status: str  # "private" | "unlisted" | "public"
    language: str | None = None
    playlist_id: str | None = None
    scheduled_publish_time: datetime | None = None


@dataclass
class UploadSession:
    """A resumable-upload session handle. `upload_url` is the Google-issued
    session URI; the caller streams file bytes to it via upload_video()."""

    upload_url: str


@dataclass
class UploadResult:
    youtube_video_id: str
    processing_status: str  # "processing" | "succeeded" | "failed"


class YouTubeProviderError(Exception):
    """Raised for quota, auth, or transport failures. Never silently swallowed."""


class YouTubeProvider(ABC):
    @abstractmethod
    async def get_oauth_authorize_url(self, state: str) -> str: ...

    @abstractmethod
    async def exchange_oauth_code(self, code: str) -> OAuthTokens: ...

    @abstractmethod
    async def refresh_oauth_token(self, refresh_token: str) -> OAuthTokens: ...

    @abstractmethod
    async def get_channel(
        self, channel_id: str | None = None, access_token: str | None = None
    ) -> ChannelData:
        """Fetch a channel by id, or the authorized user's own channel ("mine")."""

    @abstractmethod
    async def list_channel_videos(
        self, channel_id: str, page_token: str | None = None, max_results: int = 50
    ) -> VideosPage: ...

    @abstractmethod
    async def get_video_details(self, video_ids: list[str]) -> list[VideoData]: ...

    @abstractmethod
    async def get_channel_analytics(
        self, channel_id: str, access_token: str, start_date: datetime, end_date: datetime
    ) -> list[AnalyticsRow]:
        """Requires an authorized OAuth token with the YouTube Analytics scope.
        Providers without authorization must raise YouTubeProviderError rather
        than fabricate numbers."""

    # --- Publishing (Growth OS: authorized upload/publish pipeline) ---

    @abstractmethod
    async def prepare_upload(
        self, access_token: str, metadata: UploadMetadata, file_size_bytes: int
    ) -> UploadSession:
        """Opens a resumable upload session. Raises YouTubeProviderError on
        quota/auth failure. Never buffers the whole file in this call."""

    @abstractmethod
    async def upload_video(
        self, upload_session: UploadSession, file_path: str, content_type: str
    ) -> UploadResult:
        """Streams file_path to the resumable session. Callers are responsible
        for deleting file_path afterwards (see temporary_media_cleanup_job) —
        this method never retains the source file."""

    @abstractmethod
    async def set_thumbnail(
        self, access_token: str, youtube_video_id: str, thumbnail_path: str
    ) -> None: ...

    @abstractmethod
    async def check_processing_status(self, access_token: str, youtube_video_id: str) -> str:
        """Returns one of: processing | succeeded | failed | terminated."""

    @abstractmethod
    async def verify_publication(self, youtube_video_id: str) -> bool:
        """Confirms the video is actually live/visible via a public read,
        independent of what the upload call claimed."""
