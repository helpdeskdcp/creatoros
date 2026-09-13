from app.core.config import Settings, get_settings
from app.modules.shorts.providers.base import TranscriptionProvider


def get_transcription_provider(settings: Settings | None = None) -> TranscriptionProvider:
    settings = settings or get_settings()
    if settings.transcription_provider == "openai":
        from app.modules.shorts.providers.openai_whisper_provider import OpenAIWhisperProvider

        return OpenAIWhisperProvider(settings.openai_api_key, settings.openai_base_url)

    from app.modules.shorts.providers.faster_whisper_provider import FasterWhisperProvider

    return FasterWhisperProvider(settings.whisper_model_size)
