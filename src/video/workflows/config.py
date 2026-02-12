"""WorkflowConfig — Pydantic model for pipeline presets."""

from pydantic import BaseModel, field_validator

from ..schemas import Language
from ..subtitle_generator import SubtitleConfig


class WorkflowConfig(BaseModel):
    """A named pipeline configuration preset.

    Each workflow captures all tunable knobs of the video generation pipeline.
    Optional fields (None) mean "use the pipeline's auto-detection logic".
    """

    # Identity
    name: str
    description: str
    version: int

    # Language
    language: Language = Language.EN

    # Voice selection (None = auto-detect from brief)
    voice_tone: str | None = None
    voice_gender: str | None = None
    voice_name: str | None = None

    # VO pacing
    vo_gap_seconds: float = 0.05

    # Music
    music_volume: float = 0.35
    music_mood: str | None = None

    # Subtitles
    subtitle_config: SubtitleConfig = SubtitleConfig()

    # Font
    font_name: str = "Montserrat-Bold"

    # UGC talking head
    ugc_enabled: bool = False
    ugc_provider: str = "hedra"

    # UGC PIP overlay (stock background + avatar corner)
    ugc_overlay: bool = False
    ugc_overlay_size: float = 0.30
    ugc_overlay_position: str = "bottom_right"
    ugc_overlay_margin: int = 40
    ugc_overlay_circle: bool = True

    @field_validator("version")
    @classmethod
    def version_non_negative(cls, v: int) -> int:
        if v < 0:
            msg = "version must be >= 0"
            raise ValueError(msg)
        return v
