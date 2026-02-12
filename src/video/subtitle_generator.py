"""
Subtitle generator for video content.

Creates timed subtitle segments from voiceover text,
outputs SRT/WebVTT formats, and builds FFmpeg subtitle filters.
"""

from pydantic import BaseModel


class TimedWord(BaseModel):
    """A single word with start/end timing."""

    word: str
    start_time: float
    end_time: float


class SubtitleSegment(BaseModel):
    """A subtitle segment (group of words) with timing."""

    text: str
    start_time: float
    end_time: float


class SubtitleConfig(BaseModel):
    """Configuration for subtitle visual rendering."""

    font_name: str = "Montserrat-Bold"
    font_size_ratio: float = 0.065  # ~70px at 1080w
    position_y_ratio: float = 0.72  # lower third
    outline_width: int = 4
    shadow_offset: int = 3
    bg_enabled: bool = True
    bg_color: tuple[int, int, int, int] = (0, 0, 0, 160)
    bg_padding: int = 16
    max_words_per_segment: int = 3
    text_color: tuple[int, int, int, int] = (255, 255, 255, 255)
    shadow_color: tuple[int, int, int, int] = (0, 0, 0, 180)
    shadow_blur_radius: int = 0


class SubtitleStyle(BaseModel):
    """Style settings for subtitle rendering."""

    font_size: int = 24
    primary_color: str = "&H00FFFFFF"
    outline_color: str = "&H00000000"
    outline_width: int = 2
    bold: bool = True
    alignment: int = 5  # ASS alignment: 5 = middle-center
    margin_v: int = 50


# =============================================================================
# Word Timing
# =============================================================================


def generate_word_timing(
    text: str,
    total_duration: float,
    start_time: float = 0.0,
) -> list[TimedWord]:
    """Distribute words proportionally across a duration.

    Each word's time slice is proportional to its character length.

    Args:
        text: The text to split into timed words.
        total_duration: Total duration in seconds.
        start_time: Offset for the first word's start time.

    Returns:
        List of TimedWord with start/end times.
    """
    words = text.split()
    if not words:
        return []

    total_chars = sum(len(w) for w in words)
    current = start_time

    result = []
    for word in words:
        word_duration = (len(word) / total_chars) * total_duration
        result.append(
            TimedWord(word=word, start_time=current, end_time=current + word_duration)
        )
        current += word_duration

    return result


# =============================================================================
# Segment Grouping
# =============================================================================


def generate_segments(
    words: list[TimedWord],
    max_words_per_segment: int = 4,
) -> list[SubtitleSegment]:
    """Group timed words into subtitle segments.

    Args:
        words: List of timed words.
        max_words_per_segment: Maximum words per subtitle chunk.

    Returns:
        List of SubtitleSegment.
    """
    if not words:
        return []

    segments = []
    for i in range(0, len(words), max_words_per_segment):
        chunk = words[i : i + max_words_per_segment]
        segments.append(
            SubtitleSegment(
                text=" ".join(w.word for w in chunk),
                start_time=chunk[0].start_time,
                end_time=chunk[-1].end_time,
            )
        )

    return segments


# =============================================================================
# SRT / VTT Output
# =============================================================================


def _format_srt_time(seconds: float) -> str:
    """Format seconds as SRT timestamp: HH:MM:SS,mmm."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _format_vtt_time(seconds: float) -> str:
    """Format seconds as VTT timestamp: HH:MM:SS.mmm."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def to_srt(segments: list[SubtitleSegment]) -> str:
    """Convert subtitle segments to SRT format.

    Args:
        segments: List of subtitle segments.

    Returns:
        SRT formatted string.
    """
    lines = []
    for i, seg in enumerate(segments, start=1):
        start = _format_srt_time(seg.start_time)
        end = _format_srt_time(seg.end_time)
        lines.append(f"{i}\n{start} --> {end}\n{seg.text}\n")

    return "\n".join(lines)


def to_vtt(segments: list[SubtitleSegment]) -> str:
    """Convert subtitle segments to WebVTT format.

    Args:
        segments: List of subtitle segments.

    Returns:
        WebVTT formatted string.
    """
    lines = ["WEBVTT\n"]
    for seg in segments:
        start = _format_vtt_time(seg.start_time)
        end = _format_vtt_time(seg.end_time)
        lines.append(f"{start} --> {end}\n{seg.text}\n")

    return "\n".join(lines)


# =============================================================================
# FFmpeg Filter
# =============================================================================


def build_ffmpeg_subtitle_filter(style: SubtitleStyle, srt_path: str) -> str:
    """Build an FFmpeg subtitles filter string.

    Args:
        style: Subtitle style configuration.
        srt_path: Path to the SRT file.

    Returns:
        FFmpeg filter string for -vf option.
    """
    force_style = (
        f"FontSize={style.font_size},"
        f"PrimaryColour={style.primary_color},"
        f"OutlineColour={style.outline_color},"
        f"Outline={style.outline_width},"
        f"Bold={1 if style.bold else 0},"
        f"Alignment={style.alignment},"
        f"MarginV={style.margin_v}"
    )
    # Escape colons in the path for FFmpeg filter syntax
    escaped_path = srt_path.replace(":", "\\:")
    return f"subtitles={escaped_path}:force_style='{force_style}'"


# =============================================================================
# Shot-Based Generation
# =============================================================================


def generate_from_shots(
    shots: list[dict],
    max_words_per_segment: int = 4,
    vo_durations: dict[int, float] | None = None,
    audio_start_times: dict[int, float] | None = None,
) -> list[SubtitleSegment]:
    """Generate subtitle segments from a shot list.

    Extracts voiceover text from each shot and creates timed
    subtitle segments. When vo_durations and audio_start_times are
    provided, subtitle timing matches the actual audio placement
    instead of using brief durations.

    Args:
        shots: List of shot dicts with audio.voiceover.text.
        max_words_per_segment: Max words per subtitle chunk.
        vo_durations: Map of shot_number -> actual VO audio duration.
        audio_start_times: Map of shot_number -> actual VO start time.

    Returns:
        Combined list of SubtitleSegment across all shots.
    """
    all_segments: list[SubtitleSegment] = []
    current_time = 0.0

    sorted_shots = sorted(shots, key=lambda s: s.get("shot_number", 0))

    for shot in sorted_shots:
        shot_num = shot.get("shot_number", 0)
        brief_duration = shot.get("duration_seconds", 0.0)
        vo_text = (
            shot.get("audio", {}).get("voiceover", {}).get("text", "")
        )

        if vo_text:
            # Use actual VO duration and start time when available
            if vo_durations and shot_num in vo_durations:
                duration = vo_durations[shot_num]
            else:
                duration = brief_duration

            if audio_start_times and shot_num in audio_start_times:
                start = audio_start_times[shot_num]
            else:
                start = current_time

            words = generate_word_timing(vo_text, duration, start_time=start)
            segments = generate_segments(words, max_words_per_segment)
            all_segments.extend(segments)

        current_time += brief_duration

    return all_segments
