"""
Platform specifications and format constants.

Defines standard video durations, platform-specific dimensions,
safe zones, and helper functions for format lookups.
"""

from pydantic import BaseModel


class FormatDuration(BaseModel):
    """Standard video format duration with shot/word counts."""

    duration_seconds: int
    min_shots: int
    max_shots: int
    vo_words: int
    structure: str


class SafeZone(BaseModel):
    """Safe zone margins in pixels (areas covered by platform UI)."""

    top: int = 0
    bottom: int = 0
    left: int = 0
    right: int = 0


class PlatformFormat(BaseModel):
    """Platform-specific video format specification."""

    platform: str
    format_name: str
    width: int
    height: int
    aspect_ratio: str
    safe_zone: SafeZone


# =============================================================================
# Standard Format Durations
# =============================================================================

FORMAT_DURATIONS: list[FormatDuration] = [
    FormatDuration(
        duration_seconds=10,
        min_shots=3,
        max_shots=4,
        vo_words=25,
        structure="Hook + message + CTA",
    ),
    FormatDuration(
        duration_seconds=15,
        min_shots=3,
        max_shots=5,
        vo_words=37,
        structure="Hook + problem + solution + CTA",
    ),
    FormatDuration(
        duration_seconds=25,
        min_shots=4,
        max_shots=7,
        vo_words=62,
        structure="Hook + problem + demo + proof + CTA",
    ),
    FormatDuration(
        duration_seconds=30,
        min_shots=5,
        max_shots=7,
        vo_words=75,
        structure="Hook + problem + demo + solution + CTA",
    ),
    FormatDuration(
        duration_seconds=45,
        min_shots=6,
        max_shots=10,
        vo_words=112,
        structure="Full narrative arc",
    ),
    FormatDuration(
        duration_seconds=60,
        min_shots=8,
        max_shots=12,
        vo_words=150,
        structure="Extended story",
    ),
    FormatDuration(
        duration_seconds=90,
        min_shots=10,
        max_shots=16,
        vo_words=225,
        structure="Long-form narrative",
    ),
]

_DURATION_MAP: dict[int, FormatDuration] = {f.duration_seconds: f for f in FORMAT_DURATIONS}

BOT_DURATIONS: list[int] = [15, 30, 60, 90]

# =============================================================================
# Platform Formats
# =============================================================================

PLATFORM_FORMATS: list[PlatformFormat] = [
    PlatformFormat(
        platform="instagram_reels",
        format_name="Instagram Reels",
        width=1080,
        height=1920,
        aspect_ratio="9:16",
        safe_zone=SafeZone(top=100, bottom=300, left=0, right=80),
    ),
    PlatformFormat(
        platform="instagram_stories",
        format_name="Instagram Stories",
        width=1080,
        height=1920,
        aspect_ratio="9:16",
        safe_zone=SafeZone(top=120, bottom=200, left=0, right=0),
    ),
    PlatformFormat(
        platform="instagram_feed",
        format_name="Instagram Feed",
        width=1080,
        height=1080,
        aspect_ratio="1:1",
        safe_zone=SafeZone(),
    ),
    PlatformFormat(
        platform="tiktok",
        format_name="TikTok",
        width=1080,
        height=1920,
        aspect_ratio="9:16",
        safe_zone=SafeZone(top=100, bottom=280, left=0, right=80),
    ),
    PlatformFormat(
        platform="youtube_shorts",
        format_name="YouTube Shorts",
        width=1080,
        height=1920,
        aspect_ratio="9:16",
        safe_zone=SafeZone(top=50, bottom=150, left=0, right=0),
    ),
    PlatformFormat(
        platform="youtube_standard",
        format_name="YouTube Standard",
        width=1920,
        height=1080,
        aspect_ratio="16:9",
        safe_zone=SafeZone(),
    ),
    PlatformFormat(
        platform="facebook_reels",
        format_name="Facebook Reels",
        width=1080,
        height=1920,
        aspect_ratio="9:16",
        safe_zone=SafeZone(top=80, bottom=250, left=0, right=60),
    ),
    PlatformFormat(
        platform="x_twitter",
        format_name="X/Twitter",
        width=1920,
        height=1080,
        aspect_ratio="16:9",
        safe_zone=SafeZone(),
    ),
    PlatformFormat(
        platform="linkedin",
        format_name="LinkedIn",
        width=1080,
        height=1080,
        aspect_ratio="1:1",
        safe_zone=SafeZone(),
    ),
]

_PLATFORM_MAP: dict[str, PlatformFormat] = {f.platform: f for f in PLATFORM_FORMATS}


# =============================================================================
# Helper Functions
# =============================================================================


def get_format_duration(duration_seconds: int) -> FormatDuration:
    """Look up a standard format duration.

    Args:
        duration_seconds: Target duration in seconds.

    Returns:
        Matching FormatDuration.

    Raises:
        ValueError: If no standard format matches.
    """
    fmt = _DURATION_MAP.get(duration_seconds)
    if fmt is None:
        valid = sorted(_DURATION_MAP.keys())
        raise ValueError(
            f"No standard format for {duration_seconds}s. Valid durations: {valid}"
        )
    return fmt


def get_bot_format_durations() -> list[FormatDuration]:
    """Return the subset of standard durations offered in the Telegram bot.

    Returns:
        List of FormatDuration for 15s, 30s, 60s, 90s.
    """
    return [_DURATION_MAP[d] for d in BOT_DURATIONS]


def get_platform_format(platform: str) -> PlatformFormat:
    """Look up a platform format specification.

    Args:
        platform: Platform identifier (e.g. "tiktok", "instagram_reels").

    Returns:
        Matching PlatformFormat.

    Raises:
        ValueError: If unknown platform.
    """
    fmt = _PLATFORM_MAP.get(platform)
    if fmt is None:
        valid = sorted(_PLATFORM_MAP.keys())
        raise ValueError(f"Unknown platform '{platform}'. Valid platforms: {valid}")
    return fmt


def get_safe_text_area(platform: str) -> dict[str, int]:
    """Calculate the safe text area for a platform.

    Returns the rectangle where text/subtitles won't be obscured
    by platform UI elements.

    Args:
        platform: Platform identifier.

    Returns:
        Dict with x, y, width, height of the safe area.
    """
    fmt = get_platform_format(platform)
    sz = fmt.safe_zone
    return {
        "x": sz.left,
        "y": sz.top,
        "width": fmt.width - sz.left - sz.right,
        "height": fmt.height - sz.top - sz.bottom,
    }


def snap_to_standard_duration(seconds: float) -> int:
    """Snap an arbitrary duration to the nearest standard format length.

    Args:
        seconds: Arbitrary duration in seconds.

    Returns:
        Nearest standard duration in seconds.
    """
    standard = sorted(_DURATION_MAP.keys())
    return min(standard, key=lambda s: abs(s - seconds))
