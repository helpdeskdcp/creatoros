"""Thin, safe wrapper around ffmpeg/ffprobe. Every call here uses
asyncio.create_subprocess_exec with an argument LIST -- never shell=True,
never string-interpolated commands -- so nothing resembling shell
injection is possible even if a caller's title/description string ended
up adjacent to a path. Callers are responsible for only ever passing
paths CreatorOS itself generated (see app.core.storage / MediaAsset) --
this module does not re-validate that, it just never gives an argument a
chance to be interpreted as anything but a literal string.
"""
import asyncio
import json
import os
from dataclasses import dataclass


class FFmpegError(Exception):
    """Raised on a real ffmpeg/ffprobe failure (bad input, unsupported
    codec, timeout). Never swallowed -- a failed probe/extract/render
    must never be reported as success."""


@dataclass
class MediaProbe:
    duration_seconds: float
    has_video: bool
    has_audio: bool
    width: int | None
    height: int | None


async def _run(args: list[str], timeout: float) -> tuple[str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise FFmpegError(f"{args[0]} timed out after {timeout}s") from exc
    if proc.returncode != 0:
        raise FFmpegError(f"{args[0]} failed (exit {proc.returncode}): {stderr.decode(errors='replace')[-2000:]}")
    return stdout.decode(errors="replace"), stderr.decode(errors="replace")


async def probe(file_path: str, *, timeout: float = 30.0) -> MediaProbe:
    """Real validation via ffprobe -- never trusts a file extension alone.
    Raises FFmpegError for anything ffprobe can't parse as media."""
    stdout, _ = await _run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", file_path,
        ],
        timeout=timeout,
    )
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise FFmpegError(f"ffprobe returned unparseable output for {file_path}") from exc

    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    duration_str = data.get("format", {}).get("duration")
    if duration_str is None:
        raise FFmpegError(f"ffprobe could not determine duration for {file_path}")
    return MediaProbe(
        duration_seconds=float(duration_str),
        has_video=video_stream is not None,
        has_audio=has_audio,
        width=int(video_stream["width"]) if video_stream and "width" in video_stream else None,
        height=int(video_stream["height"]) if video_stream and "height" in video_stream else None,
    )


async def extract_audio(video_path: str, output_wav_path: str, *, timeout: float = 300.0) -> None:
    """16kHz mono WAV -- the standard input format transcription models
    (including faster-whisper) expect; also keeps the intermediate file
    small regardless of source video bitrate."""
    os.makedirs(os.path.dirname(output_wav_path), exist_ok=True)
    await _run(
        [
            "ffmpeg", "-y", "-i", video_path, "-vn", "-ar", "16000", "-ac", "1",
            "-f", "wav", output_wav_path,
        ],
        timeout=timeout,
    )
    if not os.path.isfile(output_wav_path) or os.path.getsize(output_wav_path) == 0:
        raise FFmpegError(f"Audio extraction produced no output for {video_path}")


async def render_vertical_clip(
    source_path: str,
    output_path: str,
    *,
    start_seconds: float,
    end_seconds: float,
    width: int = 1080,
    height: int = 1920,
    subtitles_srt_path: str | None = None,
    timeout: float = 600.0,
) -> None:
    """Crops/scales the [start, end] window of source_path into a 9:16
    (or any configured resolution) clip, optionally burning in captions
    via libass. scale+crop (not pad) so a landscape source fills the
    vertical frame rather than showing letterboxing -- matches how real
    Shorts/Reels look; center-crop is a reasonable default that can be
    made configurable later without changing this function's contract.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    duration = end_seconds - start_seconds
    if duration <= 0:
        raise FFmpegError(f"Invalid clip window: start={start_seconds} end={end_seconds}")

    vf_parts = [
        f"scale={width}:{height}:force_original_aspect_ratio=increase",
        f"crop={width}:{height}",
    ]
    if subtitles_srt_path:
        if not os.path.isfile(subtitles_srt_path):
            raise FFmpegError(f"Subtitles file not found: {subtitles_srt_path}")
        # ffmpeg filter syntax requires escaping ':' in Windows-style paths
        # and treats ',' as a filter-option separator; escape both defensively.
        escaped = subtitles_srt_path.replace("\\", "\\\\").replace(":", "\\:").replace(",", "\\,")
        vf_parts.append(f"subtitles={escaped}")

    await _run(
        [
            "ffmpeg", "-y",
            "-ss", str(start_seconds), "-i", source_path, "-t", str(duration),
            "-vf", ",".join(vf_parts),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            output_path,
        ],
        timeout=timeout,
    )
    if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
        raise FFmpegError(f"Rendering produced no output for {source_path}")
