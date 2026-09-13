"""Real integration tests against real ffmpeg/ffprobe -- no mocking.
Test fixtures are synthesized with ffmpeg's own lavfi test-pattern/tone
generators so no external video asset is needed and CI never depends on
network access for a fixture file."""
import asyncio
import os

import pytest

from app.core.ffmpeg import FFmpegError, extract_audio, probe, render_vertical_clip


async def _make_test_video(path: str, duration: int = 3, width: int = 640, height: int = 360) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"testsrc=size={width}x{height}:duration={duration}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
        "-c:v", "libx264", "-c:a", "aac", "-shortest", path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    assert proc.returncode == 0, stderr.decode()


@pytest.mark.asyncio
async def test_probe_reads_real_video_metadata(tmp_path):
    video_path = str(tmp_path / "test.mp4")
    await _make_test_video(video_path, duration=3, width=640, height=360)

    result = await probe(video_path)

    assert result.has_video is True
    assert result.has_audio is True
    assert result.width == 640
    assert result.height == 360
    assert 2.5 < result.duration_seconds < 3.5


@pytest.mark.asyncio
async def test_probe_rejects_a_non_media_file(tmp_path):
    fake = tmp_path / "not_a_video.mp4"
    fake.write_bytes(b"this is definitely not a real video file")

    with pytest.raises(FFmpegError):
        await probe(str(fake))


@pytest.mark.asyncio
async def test_extract_audio_produces_a_real_wav_file(tmp_path):
    video_path = str(tmp_path / "test.mp4")
    await _make_test_video(video_path, duration=2)
    audio_path = str(tmp_path / "audio" / "out.wav")

    await extract_audio(video_path, audio_path)

    assert os.path.isfile(audio_path)
    probed = await probe(audio_path)
    assert probed.has_audio is True
    assert probed.has_video is False
    assert 1.5 < probed.duration_seconds < 2.5


@pytest.mark.asyncio
async def test_render_vertical_clip_produces_correct_dimensions(tmp_path):
    video_path = str(tmp_path / "source.mp4")
    await _make_test_video(video_path, duration=5, width=1280, height=720)  # landscape source
    output_path = str(tmp_path / "clips" / "short.mp4")

    await render_vertical_clip(video_path, output_path, start_seconds=1.0, end_seconds=3.0, width=360, height=640)

    assert os.path.isfile(output_path)
    result = await probe(output_path)
    assert result.width == 360
    assert result.height == 640
    assert 1.5 < result.duration_seconds < 2.5  # ~2s clip (3.0 - 1.0)


@pytest.mark.asyncio
async def test_render_vertical_clip_burns_in_captions(tmp_path):
    video_path = str(tmp_path / "source.mp4")
    await _make_test_video(video_path, duration=3)
    srt_path = tmp_path / "captions.srt"
    srt_path.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello world\n")
    output_path = str(tmp_path / "captioned.mp4")

    await render_vertical_clip(
        video_path, output_path, start_seconds=0.0, end_seconds=2.0,
        subtitles_srt_path=str(srt_path),
    )

    assert os.path.isfile(output_path)
    result = await probe(output_path)
    assert result.has_video is True


@pytest.mark.asyncio
async def test_render_vertical_clip_rejects_invalid_window(tmp_path):
    video_path = str(tmp_path / "source.mp4")
    await _make_test_video(video_path, duration=2)

    with pytest.raises(FFmpegError):
        await render_vertical_clip(
            video_path, str(tmp_path / "out.mp4"), start_seconds=2.0, end_seconds=1.0
        )


@pytest.mark.asyncio
async def test_render_vertical_clip_rejects_missing_subtitles_file(tmp_path):
    video_path = str(tmp_path / "source.mp4")
    await _make_test_video(video_path, duration=2)

    with pytest.raises(FFmpegError):
        await render_vertical_clip(
            video_path, str(tmp_path / "out.mp4"), start_seconds=0.0, end_seconds=1.0,
            subtitles_srt_path=str(tmp_path / "does_not_exist.srt"),
        )
