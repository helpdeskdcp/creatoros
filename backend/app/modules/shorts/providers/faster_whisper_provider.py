"""Real local transcription via faster-whisper (CTranslate2-backed --
chosen over openai-whisper specifically because it runs meaningfully
faster on CPU-only hardware with no PyTorch dependency, which matters on
a constrained VPS). Smoke-tested manually: the 'tiny' model loads in
~2.6s and transcribes a few seconds of audio in under 1s on a 2-vCPU box.
"""
import asyncio

from app.modules.shorts.providers.base import (
    TranscriptionProvider,
    TranscriptionProviderError,
    TranscriptionResult,
    TranscriptSegmentResult,
)

_model_cache: dict[str, object] = {}


def _get_model(model_size: str):
    if model_size not in _model_cache:
        from faster_whisper import WhisperModel

        _model_cache[model_size] = WhisperModel(model_size, device="cpu", compute_type="int8")
    return _model_cache[model_size]


class FasterWhisperProvider(TranscriptionProvider):
    name = "faster-whisper"

    def __init__(self, model_size: str = "tiny") -> None:
        self._model_size = model_size

    def _transcribe_sync(self, audio_file_path: str) -> TranscriptionResult:
        model = _get_model(self._model_size)
        segments_iter, info = model.transcribe(audio_file_path)
        segments = [
            TranscriptSegmentResult(start_seconds=s.start, end_seconds=s.end, text=s.text.strip())
            for s in segments_iter
        ]
        return TranscriptionResult(
            full_text=" ".join(s.text for s in segments).strip(),
            language=info.language,
            segments=segments,
            provider=f"{self.name}:{self._model_size}",
        )

    async def transcribe(self, audio_file_path: str) -> TranscriptionResult:
        try:
            # faster-whisper's transcribe() is synchronous/CPU-bound --
            # never call it directly from an async context, or it blocks
            # the whole event loop for the entire transcription duration.
            return await asyncio.to_thread(self._transcribe_sync, audio_file_path)
        except Exception as exc:  # noqa: BLE001 -- ctranslate2/whisper raise many distinct types
            raise TranscriptionProviderError(f"faster-whisper transcription failed: {exc}") from exc
