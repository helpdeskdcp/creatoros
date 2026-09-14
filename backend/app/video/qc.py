"""Automated quality control for a downloaded video generation output.
Reuses app.core.ffmpeg.probe() (the same ffprobe wrapper the shorts/media
pipeline already relies on) rather than a second media-inspection layer.

Explicitly NOT implemented this pass (would need frame-level decoding, not
just stream metadata): black-frame detection, frozen-frame detection,
corrupted-mid-file-frame detection. QCResult.warnings surfaces this
limitation rather than silently claiming a check that isn't real -- see
app.modules.thumbnail_vision for the same honesty convention.
"""
import os
from dataclasses import dataclass, field

from app.core.ffmpeg import FFmpegError, MediaProbe, probe

_DURATION_TOLERANCE_S = 1.5
_MIN_FILE_SIZE_BYTES = 1024


@dataclass
class QCResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    probe: MediaProbe | None = None


async def run_qc(
    file_path: str,
    *,
    expected_duration_s: int | None,
    expected_resolution: str | None,
    expected_audio: bool,
) -> QCResult:
    reasons: list[str] = []
    warnings: list[str] = [
        "Black-frame, frozen-frame, and corrupted-mid-file-frame detection "
        "are not implemented -- QC here validates container/stream metadata "
        "only (existence, decodability, duration, resolution, audio)."
    ]

    if not os.path.isfile(file_path):
        return QCResult(passed=False, reasons=["Output file does not exist"], warnings=warnings)
    size = os.path.getsize(file_path)
    if size < _MIN_FILE_SIZE_BYTES:
        reasons.append(f"Output file is suspiciously small ({size} bytes)")

    try:
        media = await probe(file_path)
    except FFmpegError as exc:
        return QCResult(passed=False, reasons=[f"File is not a valid/decodable video: {exc}"], warnings=warnings)

    if not media.has_video:
        reasons.append("No video stream found in output")
    if expected_audio and not media.has_audio:
        reasons.append("Audio was requested but the output has no audio stream")
    if expected_duration_s and abs(media.duration_seconds - expected_duration_s) > _DURATION_TOLERANCE_S:
        reasons.append(
            f"Duration mismatch: expected ~{expected_duration_s}s, got {media.duration_seconds:.1f}s"
        )
    if expected_resolution and media.height:
        expected_height = _resolution_to_height(expected_resolution)
        if expected_height and abs(media.height - expected_height) > expected_height * 0.15:
            reasons.append(
                f"Resolution mismatch: expected ~{expected_resolution} (~{expected_height}p), "
                f"got {media.width}x{media.height}"
            )

    return QCResult(passed=len(reasons) == 0, reasons=reasons, warnings=warnings, probe=media)


def _resolution_to_height(resolution: str) -> int | None:
    mapping = {"480p": 480, "720p": 720, "768p": 768, "1080p": 1080, "1K": 1024, "2K": 1440, "4K": 2160}
    return mapping.get(resolution)
