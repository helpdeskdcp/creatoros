"""Provider factory: the only place that decides mock vs. real YouTube access."""
from app.core.config import Settings, get_settings
from app.modules.channels.providers.base import YouTubeProvider
from app.modules.channels.providers.mock import MockYouTubeProvider
from app.modules.channels.providers.youtube_data_api import YouTubeDataAPIProvider


def get_youtube_provider(settings: Settings | None = None) -> YouTubeProvider:
    settings = settings or get_settings()
    if settings.youtube_configured:
        return YouTubeDataAPIProvider(settings)
    return MockYouTubeProvider()
