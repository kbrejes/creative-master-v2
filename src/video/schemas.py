"""
Schemas and data models for Technical Director.
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# =============================================================================
# Enums
# =============================================================================


class Language(StrEnum):
    """Supported output languages."""

    EN = "en"
    RU = "ru"
    ES = "es"
    FR = "fr"
    DE = "de"
    PT = "pt"
    IT = "it"


LANGUAGE_LOCALE_MAP: dict[str, str] = {
    "en": "en-US",
    "ru": "ru-RU",
    "es": "es-ES",
    "fr": "fr-FR",
    "de": "de-DE",
    "pt": "pt-BR",
    "it": "it-IT",
}


class VisualType(StrEnum):
    """Types of visual assets."""
    STOCK = "stock"
    AI_GENERATED = "ai_generated"
    SCREEN_RECORDING = "screen_recording"
    BRAND_ASSET = "brand_asset"
    TEXT_OVERLAY = "text_overlay"
    UGC_TALKING_HEAD = "ugc_talking_head"


class AudioType(StrEnum):
    """Types of audio assets."""
    VOICEOVER = "voiceover"
    MUSIC = "music"
    SOUND_EFFECT = "sound_effect"
    SILENCE = "silence"


class ToolHealth(StrEnum):
    """Health status of external tools."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


class TransitionType(StrEnum):
    """Video transition types."""
    CUT = "cut"
    FADE = "fade"
    SWIPE = "swipe"
    ZOOM = "zoom"
    DISSOLVE = "dissolve"


class TextPosition(StrEnum):
    """Text overlay positions."""
    TOP_CENTER = "top_center"
    CENTER = "center"
    BOTTOM_CENTER = "bottom_center"
    TOP_LEFT = "top_left"
    TOP_RIGHT = "top_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_RIGHT = "bottom_right"


class TextAnimation(StrEnum):
    """Text overlay animations."""
    NONE = "none"
    FADE = "fade"
    POP = "pop"
    TYPE_ON = "type_on"
    SLIDE = "slide"


# =============================================================================
# Visual Specifications
# =============================================================================


class VisualSpec(BaseModel):
    """Specification for a visual element in a shot."""
    type: VisualType
    description: str = ""
    search_terms: list[str] = Field(default_factory=list)
    generation_prompt: str = ""
    asset_refs: list[str] = Field(default_factory=list)
    camera: str = ""
    transition_in: TransitionType = TransitionType.CUT
    transition_out: TransitionType = TransitionType.CUT


class TextOverlaySpec(BaseModel):
    """Specification for text overlay."""
    text: str
    position: TextPosition = TextPosition.BOTTOM_CENTER
    animation: TextAnimation = TextAnimation.FADE
    start_time: float = 0.0
    duration: float = 2.0
    font_size: int = 48
    font_color: str = "#FFFFFF"
    background_color: str | None = None


# =============================================================================
# Audio Specifications
# =============================================================================


class VoiceoverSpec(BaseModel):
    """Specification for voiceover."""
    text: str
    tone: str = "conversational"
    emphasis: list[str] = Field(default_factory=list)
    voice_id: str = ""


class MusicSpec(BaseModel):
    """Specification for background music."""
    style: str = "upbeat"
    volume: float = 0.3  # 0.0 - 1.0
    fade_in: float = 0.5
    fade_out: float = 1.0


class AudioSpec(BaseModel):
    """Specification for audio in a shot."""
    voiceover: VoiceoverSpec | None = None
    music: MusicSpec | None = None
    sfx: list[str] = Field(default_factory=list)


# =============================================================================
# Shot Specification
# =============================================================================


class ShotSpec(BaseModel):
    """Complete specification for a single shot."""
    shot_number: int
    shot_name: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    duration_seconds: float

    visual: VisualSpec
    audio: AudioSpec = Field(default_factory=AudioSpec)
    text_overlay: TextOverlaySpec | None = None


# =============================================================================
# Creative Brief (Input)
# =============================================================================


class BriefSpecifications(BaseModel):
    """Technical specifications for the output."""
    total_duration: float
    aspect_ratio: str = "9:16"
    resolution: str = "1080x1920"
    fps: int = 30
    platforms: list[str] = Field(default_factory=lambda: ["tiktok", "instagram_reels"])


class BriefConstraints(BaseModel):
    """Constraints from the brief."""
    must_include: list[str] = Field(default_factory=list)
    must_avoid: list[str] = Field(default_factory=list)
    compliance_notes: list[str] = Field(default_factory=list)


class CreativeBrief(BaseModel):
    """Complete creative brief input to Technical Director."""
    brief_id: str
    campaign_id: str = ""
    brand_id: str

    shot_list: list[ShotSpec]
    specifications: BriefSpecifications
    constraints: BriefConstraints = Field(default_factory=BriefConstraints)

    references: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Asset Records
# =============================================================================


class AssetRecord(BaseModel):
    """Record of a gathered or generated asset."""
    asset_id: str
    shot_number: int
    type: str  # "stock_video", "ai_image", "voiceover", etc.
    tool: str  # "pexels", "dalle", "elevenlabs", etc.
    source_id: str = ""  # ID from the source (e.g., pexels video ID)
    path: str  # Local path to downloaded/generated asset
    license: str = ""
    cost: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Tool Configuration
# =============================================================================


class ToolConfig(BaseModel):
    """Configuration for an external tool."""
    name: str
    type: str  # "stock", "ai_generation", "tts", "composition"
    primary: bool = True
    cost_per_use: float = 0.0
    health: ToolHealth = ToolHealth.UNKNOWN
    fallback: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Composition Log
# =============================================================================


class CompositionLog(BaseModel):
    """Log of the composition process."""
    shots_processed: int = 0
    shots_successful: int = 0
    shots_with_fallback: int = 0

    assets_used: list[AssetRecord] = Field(default_factory=list)
    audio_assets: list[AssetRecord] = Field(default_factory=list)

    total_cost: float = 0.0

    fallbacks_used: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


# =============================================================================
# Render Output
# =============================================================================


class VideoOutput(BaseModel):
    """Video file output details."""
    path: str
    format: str = "mp4"
    codec: str = "h264"
    resolution: str
    duration_seconds: float
    fps: int = 30
    bitrate_kbps: int = 8000
    file_size_mb: float = 0.0


class ThumbnailOutput(BaseModel):
    """Thumbnail output details."""
    path: str
    resolution: str = "1080x1920"
    timestamp_source: float = 0.0


class SubtitlesOutput(BaseModel):
    """Subtitles output details."""
    path: str
    language: str = "en"
    word_count: int = 0


class OutputFiles(BaseModel):
    """All output files from rendering."""
    video: VideoOutput
    thumbnail: ThumbnailOutput | None = None
    subtitles: SubtitlesOutput | None = None


class RenderOutput(BaseModel):
    """Complete output from Technical Director."""
    render_id: str
    brief_id: str
    rendered_at: str

    output_files: OutputFiles
    composition_log: CompositionLog

    validation: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Asset Requirements (Parsed from Brief)
# =============================================================================


class AssetRequirement(BaseModel):
    """Requirement for a single asset."""
    shot_number: int
    visual_type: VisualType
    description: str = ""
    search_terms: list[str] = Field(default_factory=list)
    generation_prompt: str = ""

    min_duration: float = 0.0
    min_resolution: tuple[int, int] = (720, 1280)
    aspect_ratio: str = "9:16"

    has_voiceover: bool = False
    voiceover_text: str = ""
    voiceover_config: dict[str, Any] = Field(default_factory=dict)

    has_text_overlay: bool = False
    text_overlay: TextOverlaySpec | None = None


class CostEstimate(BaseModel):
    """Cost estimate for rendering a brief."""
    total_cost: float
    breakdown: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
