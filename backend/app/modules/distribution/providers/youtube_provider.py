"""The only DistributionProvider concretely wired to a real API: it delegates
to the existing YouTubeProvider (app.modules.channels.providers) rather than
opening a second YouTube integration, per the no-duplicate-systems rule."""
from app.modules.channels.providers.base import UploadMetadata, YouTubeProvider
from app.modules.distribution.providers.base import (
    DistributionProvider,
    DistributionProviderError,
    PlatformMetrics,
    PublishResult,
)


class YouTubeDistributionProvider(DistributionProvider):
    name = "YOUTUBE"

    def __init__(self, youtube_provider: YouTubeProvider, access_token: str):
        self._provider = youtube_provider
        self._access_token = access_token

    async def connect(self, auth_code: str) -> None:
        await self._provider.exchange_oauth_code(auth_code)

    async def validate(self, asset: dict) -> list[str]:
        problems = []
        if not asset.get("title"):
            problems.append("Missing title")
        if len(asset.get("title", "")) > 100:
            problems.append("Title exceeds 100 characters")
        if not asset.get("file_path"):
            problems.append("Missing source file_path")
        return problems

    async def prepare(self, asset: dict) -> dict:
        metadata = UploadMetadata(
            title=asset["title"],
            description=asset.get("caption", ""),
            tags=asset.get("tags", []),
            category_id=asset.get("category_id", "22"),
            privacy_status=asset.get("privacy_status", "private"),
        )
        session = await self._provider.prepare_upload(
            self._access_token, metadata, asset.get("file_size_bytes", 0)
        )
        return {"upload_url": session.upload_url}

    async def publish(self, asset: dict) -> PublishResult:
        problems = await self.validate(asset)
        if problems:
            raise DistributionProviderError(f"Cannot publish: {', '.join(problems)}")
        prepared = await self.prepare(asset)
        from app.modules.channels.providers.base import UploadSession

        result = await self._provider.upload_video(
            UploadSession(upload_url=prepared["upload_url"]), asset["file_path"], "video/*"
        )
        return PublishResult(platform_post_id=result.youtube_video_id, status=result.processing_status)

    async def schedule(self, asset: dict, publish_at) -> PublishResult:
        asset = {**asset, "privacy_status": "private"}
        return await self.publish(asset)

    async def status(self, platform_post_id: str) -> str:
        return await self._provider.check_processing_status(self._access_token, platform_post_id)

    async def metrics(self, platform_post_id: str) -> PlatformMetrics:
        return PlatformMetrics(views=None, engagement=None, clicks=None, attribution_quality="UNAVAILABLE")

    async def disconnect(self) -> None:
        return None
