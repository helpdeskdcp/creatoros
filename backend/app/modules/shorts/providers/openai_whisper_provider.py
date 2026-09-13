"""TranscriptionProvider backed by OpenAI's hosted Whisper API -- the
alternative to the local faster-whisper model for deployments that would
rather pay per-request than run inference on their own CPU. Reuses the
existing OPENAI_API_KEY setting (app.ai already depends on it for text
generation) rather than inventing a second credential."""
import httpx

from app.modules.shorts.providers.base import (
    TranscriptionProvider,
    TranscriptionProviderError,
    TranscriptionResult,
    TranscriptSegmentResult,
)


class OpenAIWhisperProvider(TranscriptionProvider):
    name = "openai-whisper"

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1") -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    async def transcribe(self, audio_file_path: str) -> TranscriptionResult:
        if not self._api_key:
            raise TranscriptionProviderError("OPENAI_API_KEY is not configured")

        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            with open(audio_file_path, "rb") as f:
                files = {"file": (audio_file_path, f, "audio/wav")}
                data = {"model": "whisper-1", "response_format": "verbose_json"}
                async with httpx.AsyncClient(timeout=300.0) as client:
                    resp = await client.post(
                        f"{self._base_url}/audio/transcriptions", headers=headers, files=files, data=data
                    )
        except httpx.TransportError as exc:
            raise TranscriptionProviderError(f"OpenAI Whisper API unreachable: {self._base_url}") from exc
        except OSError as exc:
            raise TranscriptionProviderError(f"Could not read audio file: {exc}") from exc

        if resp.status_code != 200:
            raise TranscriptionProviderError(f"OpenAI Whisper API returned {resp.status_code}: {resp.text}")

        body = resp.json()
        segments = [
            TranscriptSegmentResult(
                start_seconds=seg["start"], end_seconds=seg["end"], text=seg["text"].strip()
            )
            for seg in body.get("segments", [])
        ]
        return TranscriptionResult(
            full_text=body.get("text", "").strip(),
            language=body.get("language"),
            segments=segments,
            provider=self.name,
        )
