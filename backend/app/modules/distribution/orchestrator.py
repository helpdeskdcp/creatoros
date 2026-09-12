"""DistributionOrchestrator: the single place that picks a DistributionProvider
per platform. Business logic (campaigns/assets) calls this, never a provider
class directly."""
from app.modules.distribution.models import Platform
from app.modules.distribution.providers.base import DistributionProvider, NotConfiguredProvider


def get_distribution_provider(platform: Platform, **kwargs) -> DistributionProvider:
    if platform == Platform.YOUTUBE:
        from app.modules.channels.providers import get_youtube_provider
        from app.modules.distribution.providers.youtube_provider import YouTubeDistributionProvider

        access_token = kwargs.get("access_token")
        if not access_token:
            raise ValueError("access_token is required for the YouTube distribution provider")
        return YouTubeDistributionProvider(get_youtube_provider(), access_token)

    # INSTAGRAM / FACEBOOK / X / LINKEDIN: not yet authorized. See
    # docs/youtube.md for what each platform's own app-review process needs.
    return NotConfiguredProvider(platform.value)
