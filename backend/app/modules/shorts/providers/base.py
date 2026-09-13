"""TranscriptionProvider: the single interface every transcription call
goes through, same pattern as AIProvider/YouTubeProvider/StorageBackend --
business logic never imports faster_whisper or calls an HTTP transcription
API directly, so swapping the local model for a hosted API (or adding a
third provider) never touches app/modules/shorts/service.py.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class TranscriptSegmentResult:
    start_seconds: float
    end_seconds: float
    text: str


@dataclass
class TranscriptionResult:
    full_text: str
    language: str | None
    segments: list[TranscriptSegmentResult]
    provider: str


class TranscriptionProviderError(Exception):
    """Raised on a real transcription failure (model load error, corrupt
    audio, provider API failure). Never swallowed."""


class TranscriptionProvider(ABC):
    name: str

    @abstractmethod
    async def transcribe(self, audio_file_path: str) -> TranscriptionResult: ...
