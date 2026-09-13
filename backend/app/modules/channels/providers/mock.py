"""Deterministic in-memory YouTubeProvider used by tests and local dev when
no YouTube credentials are configured. Never used in production — main.py
wires the real provider whenever YOUTUBE_CLIENT_ID/SECRET are set.
"""
from datetime import UTC, datetime, timedelta

from app.modules.channels.providers.base import (
    AnalyticsRow,
    ChannelData,
    OAuthTokens,
    UploadMetadata,
    UploadResult,
    UploadSession,
    VideoData,
    VideosPage,
    YouTubeProvider,
)


class MockYouTubeProvider(YouTubeProvider):
    def __init__(self) -> None:
        self._now = datetime.now(UTC)
        # Lets update_video_metadata/get_video_details genuinely round-trip
        # in tests (propose -> execute -> verify) instead of get_video_details
        # always returning the same static value regardless of prior calls.
        self._video_state: dict[str, dict] = {}

    def _video_snippet(self, video_id: str) -> dict:
        return self._video_state.setdefault(
            video_id,
            {
                "title": f"Mock Video {video_id}",
                "description": "Mock description",
                "tags": ["mock"],
                "category_id": "27",
            },
        )

    async def get_oauth_authorize_url(self, state: str) -> str:
        return f"https://mock.youtube.local/oauth/authorize?state={state}"

    async def exchange_oauth_code(self, code: str) -> OAuthTokens:
        return OAuthTokens(
            access_token=f"mock-access-{code}",
            refresh_token=f"mock-refresh-{code}",
            expires_at=self._now + timedelta(hours=1),
        )

    async def refresh_oauth_token(self, refresh_token: str) -> OAuthTokens:
        return OAuthTokens(
            access_token="mock-access-refreshed",
            refresh_token=refresh_token,
            expires_at=self._now + timedelta(hours=1),
        )

    async def get_channel(
        self, channel_id: str | None = None, access_token: str | None = None
    ) -> ChannelData:
        cid = channel_id or "UC_mock_demo_channel"
        return ChannelData(
            youtube_channel_id=cid,
            title="Demo Creator Channel",
            description="A mock channel used for local development and tests.",
            thumbnail_url="https://mock.youtube.local/thumb.jpg",
            country="US",
            subscriber_count=12000,
            view_count=1_500_000,
            video_count=42,
        )

    async def list_channel_videos(
        self, channel_id: str, page_token: str | None = None, max_results: int = 50
    ) -> VideosPage:
        videos = [
            VideoData(
                youtube_video_id=f"mockvid{i:03d}",
                title=f"Mock Video {i}",
                description="Mock description",
                thumbnail_url="https://mock.youtube.local/thumb.jpg",
                published_at=self._now - timedelta(days=i * 3),
                duration_seconds=600 if i % 3 else 45,
                category_id="27",
                tags=["mock", "demo"],
                view_count=1000 * (i + 1),
                like_count=50 * (i + 1),
                comment_count=5 * (i + 1),
                is_short=not bool(i % 3),
            )
            for i in range(1, 11)
        ]
        return VideosPage(videos=videos, next_page_token=None)

    async def get_video_details(self, video_ids: list[str]) -> list[VideoData]:
        results = []
        for vid in video_ids:
            snippet = self._video_snippet(vid)
            results.append(
                VideoData(
                    youtube_video_id=vid,
                    title=snippet["title"],
                    description=snippet["description"],
                    thumbnail_url="https://mock.youtube.local/thumb.jpg",
                    published_at=self._now - timedelta(days=1),
                    duration_seconds=600,
                    category_id=snippet["category_id"],
                    tags=snippet["tags"],
                    view_count=1000,
                    like_count=50,
                    comment_count=5,
                )
            )
        return results

    async def update_video_metadata(
        self,
        access_token: str,
        youtube_video_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
    ) -> VideoData:
        snippet = self._video_snippet(youtube_video_id)
        if title is not None:
            snippet["title"] = title
        if description is not None:
            snippet["description"] = description
        if tags is not None:
            snippet["tags"] = tags
        return VideoData(
            youtube_video_id=youtube_video_id,
            title=snippet["title"],
            description=snippet["description"],
            thumbnail_url="https://mock.youtube.local/thumb.jpg",
            published_at=self._now - timedelta(days=1),
            duration_seconds=600,
            category_id=snippet["category_id"],
            tags=snippet["tags"],
        )

    async def get_channel_analytics(
        self, channel_id: str, access_token: str, start_date: datetime, end_date: datetime
    ) -> list[AnalyticsRow]:
        """Deterministic sample data so OAuth-connected mock channels exercise
        the same subscriber-growth pipeline real channels do -- an empty
        list here would make it impossible to test/dev that pipeline at all
        without live Google credentials."""
        return [
            AnalyticsRow(
                video_youtube_id=f"mockvid{i:03d}",
                date=start_date + timedelta(days=1),
                views=200 * i,
                average_view_duration_seconds=45.0 + i,
                average_view_percentage=40.0 + i,
                estimated_ctr=None,
                subscribers_gained=2 * i,
            )
            for i in range(1, 11)
        ]

    async def prepare_upload(
        self, access_token: str, metadata: UploadMetadata, file_size_bytes: int
    ) -> UploadSession:
        return UploadSession(upload_url="https://mock.youtube.local/upload/session-1")

    async def upload_video(
        self, upload_session: UploadSession, file_path: str, content_type: str
    ) -> UploadResult:
        return UploadResult(youtube_video_id="mockuploadvid", processing_status="succeeded")

    async def set_thumbnail(
        self, access_token: str, youtube_video_id: str, thumbnail_path: str
    ) -> None:
        return None

    async def check_processing_status(self, access_token: str, youtube_video_id: str) -> str:
        return "succeeded"

    async def verify_publication(self, youtube_video_id: str) -> bool:
        return True
