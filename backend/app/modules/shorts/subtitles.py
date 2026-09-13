"""Generates a real .srt file from transcript segments, re-timed relative
to a clip's own start -- burned in via app.core.ffmpeg's libass filter."""


def _format_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def generate_srt(
    segments: list, clip_start_seconds: float, clip_end_seconds: float
) -> str:
    """`segments` have absolute start/end/text (as stored in
    TranscriptSegment). Only segments overlapping [clip_start,
    clip_end] are included, re-timed to be relative to clip_start so
    they line up with the rendered (trimmed) clip, not the source
    video's original timeline."""
    lines = []
    index = 1
    for seg in segments:
        if seg.end_seconds <= clip_start_seconds or seg.start_seconds >= clip_end_seconds:
            continue
        rel_start = max(seg.start_seconds, clip_start_seconds) - clip_start_seconds
        rel_end = min(seg.end_seconds, clip_end_seconds) - clip_start_seconds
        if rel_end <= rel_start:
            continue
        lines.append(str(index))
        lines.append(f"{_format_timestamp(rel_start)} --> {_format_timestamp(rel_end)}")
        lines.append(seg.text.strip())
        lines.append("")
        index += 1
    return "\n".join(lines)
