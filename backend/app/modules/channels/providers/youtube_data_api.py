"""Real YouTubeProvider backed by the YouTube Data API v3 / Analytics API v2
and Google's OAuth2 token endpoint, implemented over plain httpx so the
dependency surface stays small and testable (no SDK "magic").

Requires YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET / YOUTUBE_REDIRECT_URI to
be configured; construction fails loudly otherwise rather than degrading
silently into fabricated data (see app.core.data_quality rule).
"""
from datetime import UTC, datetime
from urllib.parse import urlencode

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import Settings
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
    YouTubeProviderError,
)

OAUTH_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
DATA_API_BASE = "https://www.googleapis.com/youtube/v3"
UPLOAD_API_BASE = "https://www.googleapis.com/upload/youtube/v3"
ANALYTICS_API_BASE = "https://youtubeanalytics.googleapis.com/v2"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

_retryable = retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(httpx.TransportError),
)


class YouTubeDataAPIProvider(YouTubeProvider):
    def __init__(self, settings: Settings) -> None:
        if not settings.youtube_configured:
            raise YouTubeProviderError(
                "YouTube OAuth is not configured (YOUTUBE_CLIENT_ID/SECRET missing). "
                "Set them in .env, or use the MockYouTubeProvider for local dev."
            )
        self._settings = settings

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=30.0)

    def _api_key_params(self) -> dict:
        return {"key": self._settings.youtube_api_key} if self._settings.youtube_api_key else {}

    async def get_oauth_authorize_url(self, state: str) -> str:
        params = {
            "client_id": self._settings.youtube_client_id,
            "redirect_uri": self._settings.youtube_redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{OAUTH_AUTHORIZE_URL}?{urlencode(params)}"

    @_retryable
    async def exchange_oauth_code(self, code: str) -> OAuthTokens:
        async with self._client() as client:
            resp = await client.post(
                OAUTH_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": self._settings.youtube_client_id,
                    "client_secret": self._settings.youtube_client_secret,
                    "redirect_uri": self._settings.youtube_redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
        if resp.status_code != 200:
            raise YouTubeProviderError(f"OAuth code exchange failed: {resp.text}")
        body = resp.json()
        return OAuthTokens(
            access_token=body["access_token"],
            refresh_token=body.get("refresh_token"),
            expires_at=datetime.now(UTC).fromtimestamp(
                datetime.now(UTC).timestamp() + body["expires_in"], tz=UTC
            ),
        )

    @_retryable
    async def refresh_oauth_token(self, refresh_token: str) -> OAuthTokens:
        async with self._client() as client:
            resp = await client.post(
                OAUTH_TOKEN_URL,
                data={
                    "refresh_token": refresh_token,
                    "client_id": self._settings.youtube_client_id,
                    "client_secret": self._settings.youtube_client_secret,
                    "grant_type": "refresh_token",
                },
            )
        if resp.status_code != 200:
            raise YouTubeProviderError(f"OAuth token refresh failed: {resp.text}")
        body = resp.json()
        return OAuthTokens(
            access_token=body["access_token"],
            refresh_token=refresh_token,
            expires_at=datetime.now(UTC).fromtimestamp(
                datetime.now(UTC).timestamp() + body["expires_in"], tz=UTC
            ),
        )

    @_retryable
    async def get_channel(
        self, channel_id: str | None = None, access_token: str | None = None
    ) -> ChannelData:
        params = {"part": "snippet,statistics", **self._api_key_params()}
        if channel_id:
            params["id"] = channel_id
        else:
            params["mine"] = "true"

        headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
        async with self._client() as client:
            resp = await client.get(f"{DATA_API_BASE}/channels", params=params, headers=headers)
        if resp.status_code == 403:
            raise YouTubeProviderError("YouTube API quota exceeded or access forbidden")
        if resp.status_code != 200:
            raise YouTubeProviderError(f"Failed to fetch channel: {resp.text}")

        items = resp.json().get("items", [])
        if not items:
            raise YouTubeProviderError("Channel not found")
        item = items[0]
        snippet, stats = item["snippet"], item.get("statistics", {})
        return ChannelData(
            youtube_channel_id=item["id"],
            title=snippet.get("title", ""),
            description=snippet.get("description"),
            thumbnail_url=(snippet.get("thumbnails", {}).get("high", {}) or {}).get("url"),
            country=snippet.get("country"),
            subscriber_count=_safe_int(stats.get("subscriberCount")),
            view_count=_safe_int(stats.get("viewCount")),
            video_count=_safe_int(stats.get("videoCount")),
        )

    @_retryable
    async def list_channel_videos(
        self, channel_id: str, page_token: str | None = None, max_results: int = 50
    ) -> VideosPage:
        # Resolve the channel's uploads playlist once, then page playlistItems —
        # this costs far less quota than search.list per the API's own guidance.
        params = {"part": "contentDetails", "id": channel_id, **self._api_key_params()}
        async with self._client() as client:
            resp = await client.get(f"{DATA_API_BASE}/channels", params=params)
            if resp.status_code != 200:
                raise YouTubeProviderError(f"Failed to resolve uploads playlist: {resp.text}")
            items = resp.json().get("items", [])
            if not items:
                raise YouTubeProviderError("Channel not found")
            uploads_playlist_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

            list_params = {
                "part": "contentDetails",
                "playlistId": uploads_playlist_id,
                "maxResults": max_results,
                **self._api_key_params(),
            }
            if page_token:
                list_params["pageToken"] = page_token
            resp = await client.get(f"{DATA_API_BASE}/playlistItems", params=list_params)
            if resp.status_code == 404 and "playlistNotFound" in resp.text:
                # A channel that has never published a public video has no
                # resolvable uploads playlist at all -- this is a real,
                # benign channel state (confirmed via production audit:
                # channels.list itself returned this same playlist id), not
                # a sync failure. Report zero videos rather than failing
                # the whole channel sync.
                return VideosPage(videos=[], next_page_token=None)
            if resp.status_code != 200:
                raise YouTubeProviderError(f"Failed to list videos: {resp.text}")
            payload = resp.json()

        video_ids = [i["contentDetails"]["videoId"] for i in payload.get("items", [])]
        videos = await self.get_video_details(video_ids) if video_ids else []
        return VideosPage(videos=videos, next_page_token=payload.get("nextPageToken"))

    @_retryable
    async def get_video_details(self, video_ids: list[str]) -> list[VideoData]:
        if not video_ids:
            return []
        results: list[VideoData] = []
        async with self._client() as client:
            for chunk_start in range(0, len(video_ids), 50):
                chunk = video_ids[chunk_start : chunk_start + 50]
                params = {
                    "part": "snippet,contentDetails,statistics",
                    "id": ",".join(chunk),
                    **self._api_key_params(),
                }
                resp = await client.get(f"{DATA_API_BASE}/videos", params=params)
                if resp.status_code != 200:
                    raise YouTubeProviderError(f"Failed to fetch video details: {resp.text}")
                for item in resp.json().get("items", []):
                    snippet = item["snippet"]
                    stats = item.get("statistics", {})
                    duration = _parse_iso8601_duration(item["contentDetails"]["duration"])
                    results.append(
                        VideoData(
                            youtube_video_id=item["id"],
                            title=snippet.get("title", ""),
                            description=snippet.get("description"),
                            thumbnail_url=(snippet.get("thumbnails", {}).get("high", {}) or {}).get(
                                "url"
                            ),
                            published_at=_parse_iso8601(snippet.get("publishedAt")),
                            duration_seconds=duration,
                            category_id=snippet.get("categoryId"),
                            tags=snippet.get("tags", []),
                            view_count=_safe_int(stats.get("viewCount")),
                            like_count=_safe_int(stats.get("likeCount")),
                            comment_count=_safe_int(stats.get("commentCount")),
                            is_short=bool(duration and duration <= 180),
                        )
                    )
        return results

    @_retryable
    async def get_channel_analytics(
        self, channel_id: str, access_token: str, start_date: datetime, end_date: datetime
    ) -> list[AnalyticsRow]:
        params = {
            "ids": f"channel=={channel_id}",
            "startDate": start_date.date().isoformat(),
            "endDate": end_date.date().isoformat(),
            "metrics": "views,averageViewDuration,averageViewPercentage,subscribersGained",
            "dimensions": "video,day",
        }
        headers = {"Authorization": f"Bearer {access_token}"}
        async with self._client() as client:
            resp = await client.get(f"{ANALYTICS_API_BASE}/reports", params=params, headers=headers)
        if resp.status_code == 403:
            raise YouTubeProviderError(
                "This channel has not authorized the YouTube Analytics scope"
            )
        if resp.status_code != 200:
            raise YouTubeProviderError(f"Failed to fetch channel analytics: {resp.text}")

        body = resp.json()
        rows = []
        for row in body.get("rows", []):
            video_id, date_str, views, avg_dur, avg_pct, subs_gained = row
            rows.append(
                AnalyticsRow(
                    video_youtube_id=video_id,
                    date=_parse_iso8601(date_str + "T00:00:00Z"),
                    views=_safe_int(views),
                    average_view_duration_seconds=float(avg_dur) if avg_dur is not None else None,
                    average_view_percentage=float(avg_pct) if avg_pct is not None else None,
                    estimated_ctr=None,  # requires the impressions-CTR report; not always granted
                    subscribers_gained=_safe_int(subs_gained),
                )
            )
        return rows

    @_retryable
    async def prepare_upload(
        self, access_token: str, metadata: UploadMetadata, file_size_bytes: int
    ) -> UploadSession:
        body = {
            "snippet": {
                "title": metadata.title,
                "description": metadata.description,
                "tags": metadata.tags,
                "categoryId": metadata.category_id,
            },
            "status": {"privacyStatus": metadata.privacy_status},
        }
        if metadata.scheduled_publish_time:
            body["status"]["publishAt"] = metadata.scheduled_publish_time.isoformat()

        headers = {
            "Authorization": f"Bearer {access_token}",
            "X-Upload-Content-Type": "video/*",
            "X-Upload-Content-Length": str(file_size_bytes),
        }
        params = {"uploadType": "resumable", "part": "snippet,status"}
        async with self._client() as client:
            resp = await client.post(
                f"{UPLOAD_API_BASE}/videos", params=params, headers=headers, json=body
            )
        if resp.status_code not in (200, 201):
            raise YouTubeProviderError(f"Failed to initiate upload session: {resp.text}")
        upload_url = resp.headers.get("Location")
        if not upload_url:
            raise YouTubeProviderError("YouTube did not return a resumable upload URL")
        return UploadSession(upload_url=upload_url)

    async def upload_video(
        self, upload_session: UploadSession, file_path: str, content_type: str
    ) -> UploadResult:
        with open(file_path, "rb") as f:
            data = f.read()
        async with self._client() as client:
            resp = await client.put(
                upload_session.upload_url,
                content=data,
                headers={"Content-Type": content_type},
            )
        if resp.status_code not in (200, 201):
            raise YouTubeProviderError(f"Video upload failed: {resp.text}")
        video_id = resp.json()["id"]
        return UploadResult(youtube_video_id=video_id, processing_status="processing")

    @_retryable
    async def set_thumbnail(
        self, access_token: str, youtube_video_id: str, thumbnail_path: str
    ) -> None:
        headers = {"Authorization": f"Bearer {access_token}"}
        with open(thumbnail_path, "rb") as f:
            data = f.read()
        async with self._client() as client:
            resp = await client.post(
                f"{UPLOAD_API_BASE}/thumbnails/set",
                params={"videoId": youtube_video_id},
                headers={**headers, "Content-Type": "image/jpeg"},
                content=data,
            )
        if resp.status_code != 200:
            raise YouTubeProviderError(f"Failed to set thumbnail: {resp.text}")

    @_retryable
    async def check_processing_status(self, access_token: str, youtube_video_id: str) -> str:
        headers = {"Authorization": f"Bearer {access_token}"}
        params = {"part": "processingDetails,status", "id": youtube_video_id}
        async with self._client() as client:
            resp = await client.get(f"{DATA_API_BASE}/videos", params=params, headers=headers)
        if resp.status_code != 200:
            raise YouTubeProviderError(f"Failed to check processing status: {resp.text}")
        items = resp.json().get("items", [])
        if not items:
            return "failed"
        processing = items[0].get("processingDetails", {}).get("processingStatus", "processing")
        mapping = {"succeeded": "succeeded", "processing": "processing", "failed": "failed"}
        return mapping.get(processing, "processing")

    @_retryable
    async def verify_publication(self, youtube_video_id: str) -> bool:
        params = {"part": "status", "id": youtube_video_id, **self._api_key_params()}
        async with self._client() as client:
            resp = await client.get(f"{DATA_API_BASE}/videos", params=params)
        if resp.status_code != 200:
            return False
        items = resp.json().get("items", [])
        if not items:
            return False
        return items[0]["status"].get("uploadStatus") == "processed"

    @_retryable
    async def update_video_metadata(
        self,
        access_token: str,
        youtube_video_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
    ) -> VideoData:
        # videos.update replaces the ENTIRE snippet resource -- fetch the
        # current one first so fields this call doesn't touch (categoryId,
        # defaultLanguage, tags when only updating title, etc.) survive.
        async with self._client() as client:
            get_resp = await client.get(
                f"{DATA_API_BASE}/videos",
                params={"part": "snippet", "id": youtube_video_id, **self._api_key_params()},
            )
            if get_resp.status_code != 200:
                raise YouTubeProviderError(f"Failed to read current snippet: {get_resp.text}")
            items = get_resp.json().get("items", [])
            if not items:
                raise YouTubeProviderError(f"Video '{youtube_video_id}' not found")
            snippet = items[0]["snippet"]

            if title is not None:
                snippet["title"] = title
            if description is not None:
                snippet["description"] = description
            if tags is not None:
                snippet["tags"] = tags

            put_resp = await client.put(
                f"{DATA_API_BASE}/videos",
                params={"part": "snippet"},
                headers={"Authorization": f"Bearer {access_token}"},
                json={"id": youtube_video_id, "snippet": snippet},
            )
        if put_resp.status_code != 200:
            raise YouTubeProviderError(f"Failed to update video metadata: {put_resp.text}")

        updated_snippet = put_resp.json()["snippet"]
        return VideoData(
            youtube_video_id=youtube_video_id,
            title=updated_snippet.get("title", ""),
            description=updated_snippet.get("description"),
            thumbnail_url=(updated_snippet.get("thumbnails", {}).get("high", {}) or {}).get("url"),
            published_at=_parse_iso8601(updated_snippet.get("publishedAt")),
            duration_seconds=None,
            category_id=updated_snippet.get("categoryId"),
            tags=updated_snippet.get("tags", []),
        )


def _safe_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_iso8601(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parse_iso8601_duration(duration: str) -> int | None:
    """Parses ISO-8601 durations like PT1H2M3S into total seconds."""
    import re

    match = re.match(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", duration)
    if not match:
        return None
    hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds
