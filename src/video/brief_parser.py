"""
Brief Parser - Extracts requirements and estimates costs from creative briefs.
"""

from typing import Any

from .schemas import (
    AssetRequirement,
    CostEstimate,
    CreativeBrief,
    ShotSpec,
    TextOverlaySpec,
    VisualType,
)


class BriefParser:
    """
    Parses creative briefs to extract asset requirements and estimate costs.
    """

    # Default costs per tool type
    DEFAULT_COSTS: dict[str, float] = {
        "stock": 0.0,
        "ai_image": 0.04,
        "ai_video": 0.50,
        "tts": 0.01,  # Per ~100 characters
        "music": 0.0,
        "sfx": 0.0,
    }

    def __init__(self, cost_config: dict[str, float] | None = None):
        """
        Initialize parser with optional custom cost configuration.

        Args:
            cost_config: Override default costs per tool type
        """
        self.costs = {**self.DEFAULT_COSTS}
        if cost_config:
            self.costs.update(cost_config)

    def extract_requirements(self, brief: dict[str, Any] | CreativeBrief) -> list[AssetRequirement]:
        """
        Extract asset requirements from each shot in the brief.

        Args:
            brief: Creative brief (dict or CreativeBrief model)

        Returns:
            List of AssetRequirement objects

        Raises:
            ValueError: If brief is missing required fields
        """
        # Handle both dict and model input
        brief_data = brief if isinstance(brief, dict) else brief.model_dump()

        # Validate required fields
        if "shot_list" not in brief_data:
            raise ValueError("Brief is missing required field: shot_list")

        if not brief_data["shot_list"]:
            raise ValueError("Brief shot_list is empty")

        requirements = []
        specs = brief_data.get("specifications", {})
        default_aspect_ratio = specs.get("aspect_ratio", "9:16")

        for shot in brief_data["shot_list"]:
            requirement = self._parse_shot_requirement(shot, default_aspect_ratio)
            requirements.append(requirement)

        return requirements

    def _parse_shot_requirement(
        self, shot: dict[str, Any] | ShotSpec, default_aspect_ratio: str
    ) -> AssetRequirement:
        """Parse a single shot into an asset requirement."""
        shot_data = shot.model_dump() if isinstance(shot, ShotSpec) else shot

        visual = shot_data.get("visual", {})
        audio = shot_data.get("audio", {})
        text_overlay = shot_data.get("text_overlay")

        # Parse visual type
        visual_type_str = visual.get("type", "stock")
        try:
            visual_type = VisualType(visual_type_str)
        except ValueError:
            visual_type = VisualType.STOCK

        # Parse voiceover
        voiceover = audio.get("voiceover", {}) if audio else {}
        has_voiceover = bool(voiceover and voiceover.get("text"))

        # Parse text overlay
        has_text_overlay = text_overlay is not None
        text_overlay_spec = None
        if has_text_overlay and isinstance(text_overlay, dict):
            text_overlay_spec = TextOverlaySpec(**text_overlay)
        elif has_text_overlay and isinstance(text_overlay, TextOverlaySpec):
            text_overlay_spec = text_overlay

        return AssetRequirement(
            shot_number=shot_data.get("shot_number", 0),
            visual_type=visual_type,
            description=visual.get("description", ""),
            search_terms=visual.get("search_terms", []),
            generation_prompt=visual.get("generation_prompt", ""),
            min_duration=shot_data.get("duration_seconds", 0),
            aspect_ratio=default_aspect_ratio,
            has_voiceover=has_voiceover,
            voiceover_text=voiceover.get("text", "") if voiceover else "",
            voiceover_config={
                "tone": voiceover.get("tone", "conversational"),
                "emphasis": voiceover.get("emphasis", []),
            } if voiceover else {},
            has_text_overlay=has_text_overlay,
            text_overlay=text_overlay_spec,
        )

    def estimate_cost(
        self,
        brief: dict[str, Any] | CreativeBrief,
        cost_per_tool: dict[str, float] | None = None,
    ) -> CostEstimate:
        """
        Estimate total cost for rendering the brief.

        Args:
            brief: Creative brief
            cost_per_tool: Optional override for cost per tool type

        Returns:
            CostEstimate with total and breakdown
        """
        costs = {**self.costs}
        if cost_per_tool:
            costs.update(cost_per_tool)

        requirements = self.extract_requirements(brief)
        breakdown: dict[str, float] = {}
        warnings: list[str] = []
        total = 0.0

        for req in requirements:
            shot_key = f"shot_{req.shot_number}"

            # Visual cost
            visual_cost = self._estimate_visual_cost(req.visual_type, costs)
            if visual_cost > 0:
                breakdown[f"{shot_key}_visual"] = visual_cost
                total += visual_cost

            # Voiceover cost
            if req.has_voiceover and req.voiceover_text:
                # Cost based on character count
                char_count = len(req.voiceover_text)
                vo_cost = costs.get("tts", 0.01) * (char_count / 100)
                breakdown[f"{shot_key}_voiceover"] = vo_cost
                total += vo_cost

        # Add warnings for expensive operations
        if total > 1.0:
            warnings.append(f"Total estimated cost (${total:.2f}) exceeds $1.00")

        ai_video_count = sum(
            1 for r in requirements if r.visual_type == VisualType.AI_GENERATED
        )
        if ai_video_count > 3:
            warnings.append(f"Multiple AI generations ({ai_video_count}) may be slow")

        return CostEstimate(
            total_cost=round(total, 4),
            breakdown=breakdown,
            warnings=warnings,
        )

    def _estimate_visual_cost(self, visual_type: VisualType, costs: dict[str, float]) -> float:
        """Estimate cost for a visual asset type."""
        cost_map = {
            VisualType.STOCK: costs.get("stock", 0.0),
            VisualType.AI_GENERATED: costs.get("ai_image", 0.04),
            VisualType.SCREEN_RECORDING: 0.0,
            VisualType.BRAND_ASSET: 0.0,
            VisualType.TEXT_OVERLAY: 0.0,
        }
        return cost_map.get(visual_type, 0.0)

    def identify_required_tools(
        self, brief: dict[str, Any] | CreativeBrief
    ) -> list[str]:
        """
        Identify which tools are needed for this brief.

        Args:
            brief: Creative brief

        Returns:
            List of tool identifiers needed
        """
        requirements = self.extract_requirements(brief)
        tools: set[str] = set()

        for req in requirements:
            # Visual tools
            if req.visual_type == VisualType.STOCK:
                tools.add("stock_video")
            elif req.visual_type == VisualType.AI_GENERATED:
                tools.add("ai_image")
                tools.add("ai_video")
            elif req.visual_type == VisualType.SCREEN_RECORDING:
                tools.add("screen_recorder")

            # Audio tools
            if req.has_voiceover:
                tools.add("tts")

        # Composition is always needed
        tools.add("compositor")

        return sorted(tools)

    def validate_brief(self, brief: dict[str, Any] | CreativeBrief) -> list[str]:
        """
        Validate brief for completeness and consistency.

        Args:
            brief: Creative brief

        Returns:
            List of validation errors (empty if valid)
        """
        errors: list[str] = []

        brief_data = brief if isinstance(brief, dict) else brief.model_dump()

        # Check required fields
        if "shot_list" not in brief_data:
            errors.append("Missing required field: shot_list")
            return errors

        if not brief_data["shot_list"]:
            errors.append("shot_list is empty")
            return errors

        # Check shot consistency
        shot_numbers = [s.get("shot_number", 0) for s in brief_data["shot_list"]]
        if len(shot_numbers) != len(set(shot_numbers)):
            errors.append("Duplicate shot numbers found")

        # Check duration
        total_duration = sum(
            s.get("duration_seconds", 0) for s in brief_data["shot_list"]
        )
        specs = brief_data.get("specifications", {})
        expected_duration = specs.get("total_duration", 0)

        if expected_duration > 0 and abs(total_duration - expected_duration) > 1.0:
            errors.append(
                f"Shot durations ({total_duration}s) don't match "
                f"expected total ({expected_duration}s)"
            )

        # Check each shot
        for i, shot in enumerate(brief_data["shot_list"]):
            shot_errors = self._validate_shot(shot, i)
            errors.extend(shot_errors)

        return errors

    def _validate_shot(self, shot: dict[str, Any], index: int) -> list[str]:
        """Validate a single shot."""
        errors: list[str] = []
        shot_id = shot.get("shot_number", index + 1)

        if "duration_seconds" not in shot or shot["duration_seconds"] <= 0:
            errors.append(f"Shot {shot_id}: Missing or invalid duration")

        if "visual" not in shot:
            errors.append(f"Shot {shot_id}: Missing visual specification")
        else:
            visual = shot["visual"]
            if "type" not in visual:
                errors.append(f"Shot {shot_id}: Missing visual type")

        return errors
