"""Workflow 1 — Serif subtitles with soft shadow, no background."""

from ..subtitle_generator import SubtitleConfig
from .config import WorkflowConfig

WORKFLOW = WorkflowConfig(
    name="Workflow 1",
    description="Serif subtitles — Libre Baskerville, black text, soft shadow",
    version=1,
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
)
