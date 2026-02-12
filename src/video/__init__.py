"""
Technical Director Agent - Renders creative briefs to video.

This module provides:
- BriefParser: Parses creative briefs and extracts requirements
- ToolSelector: Selects appropriate tools based on requirements
- AssetGatherer: Gathers stock assets from APIs
- AssetGenerator: Generates assets via AI (images, video, TTS)
- Compositor: Assembles video using FFmpeg
- OutputValidator: Validates rendered output
- TechnicalDirectorAgent: Main orchestrating agent
"""

from .agent import TechnicalDirectorAgent
from .asset_gatherer import AssetGatherer
from .asset_generator import AssetGenerator
from .brief_parser import BriefParser
from .compositor import Compositor
from .output_validator import OutputValidator
from .schemas import (
    AssetRecord,
    AssetRequirement,
    AudioType,
    CostEstimate,
    CreativeBrief,
    RenderOutput,
    ShotSpec,
    TextAnimation,
    TextOverlaySpec,
    TextPosition,
    ToolConfig,
    ToolHealth,
    TransitionType,
    VisualType,
)
from .tool_selector import ToolSelector

__all__ = [
    # Main agent
    "TechnicalDirectorAgent",
    # Components
    "BriefParser",
    "ToolSelector",
    "AssetGatherer",
    "AssetGenerator",
    "Compositor",
    "OutputValidator",
    # Schemas
    "AssetRecord",
    "AssetRequirement",
    "AudioType",
    "CostEstimate",
    "CreativeBrief",
    "RenderOutput",
    "ShotSpec",
    "TextAnimation",
    "TextOverlaySpec",
    "TextPosition",
    "ToolConfig",
    "ToolHealth",
    "TransitionType",
    "VisualType",
]
