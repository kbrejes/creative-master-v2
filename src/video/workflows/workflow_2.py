"""Workflow 2 — Stock footage with PIP avatar overlay and serif subtitles."""

from ..subtitle_generator import SubtitleConfig
from .config import WorkflowConfig

WORKFLOW = WorkflowConfig(
    name="UGC PIP Overlay",
    description="Stock footage with picture-in-picture avatar and serif subtitles",
    version=2,
    font_name="LibreBaskerville-Regular",
    subtitle_config=SubtitleConfig(
        font_name="LibreBaskerville-Regular",
        outline_width=0,
        shadow_offset=4,
        shadow_blur_radius=6,
        shadow_color=(0, 0, 0, 120),
        bg_enabled=False,
        text_color=(0, 0, 0, 255),
    ),
    ugc_enabled=True,
    ugc_provider="replicate",
    ugc_overlay=True,
)
