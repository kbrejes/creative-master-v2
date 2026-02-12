"""
Tool Selector - Selects appropriate tools based on requirements, health, and budget.
"""

from typing import Any

from .schemas import (
    AssetRequirement,
    ToolConfig,
    ToolHealth,
    VisualType,
)


class ToolSelector:
    """
    Selects optimal tools for each asset requirement based on:
    - Asset type requirements
    - Tool availability/health
    - Budget constraints
    - Historical success rates
    """

    # Default tool registry with fallback chains
    DEFAULT_TOOLS: dict[str, list[ToolConfig]] = {
        "stock_video": [
            ToolConfig(
                name="pexels",
                type="stock",
                primary=True,
                cost_per_use=0.0,
                fallback="storyblocks",
            ),
            ToolConfig(
                name="storyblocks",
                type="stock",
                primary=False,
                cost_per_use=0.0,
                fallback="pixabay",
            ),
            ToolConfig(
                name="pixabay",
                type="stock",
                primary=False,
                cost_per_use=0.0,
            ),
        ],
        "stock_image": [
            ToolConfig(
                name="unsplash",
                type="stock",
                primary=True,
                cost_per_use=0.0,
                fallback="pexels",
            ),
            ToolConfig(
                name="pexels",
                type="stock",
                primary=False,
                cost_per_use=0.0,
            ),
        ],
        "ai_image": [
            ToolConfig(
                name="dalle",
                type="ai_generation",
                primary=True,
                cost_per_use=0.04,
                fallback="stable_diffusion",
            ),
            ToolConfig(
                name="midjourney",
                type="ai_generation",
                primary=False,
                cost_per_use=0.05,
                fallback="stable_diffusion",
            ),
            ToolConfig(
                name="stable_diffusion",
                type="ai_generation",
                primary=False,
                cost_per_use=0.0,  # Local
            ),
        ],
        "ai_video": [
            ToolConfig(
                name="runway",
                type="ai_generation",
                primary=True,
                cost_per_use=0.50,
                fallback="pika",
            ),
            ToolConfig(
                name="pika",
                type="ai_generation",
                primary=False,
                cost_per_use=0.30,
                fallback="hunyuan",
            ),
            ToolConfig(
                name="hunyuan",
                type="ai_generation",
                primary=False,
                cost_per_use=0.0,  # Local
            ),
        ],
        "tts": [
            ToolConfig(
                name="edge_tts",
                type="tts",
                primary=True,
                cost_per_use=0.0,  # Free
                fallback="elevenlabs",
            ),
            ToolConfig(
                name="elevenlabs",
                type="tts",
                primary=False,
                cost_per_use=0.01,
                fallback="openai_tts",
            ),
            ToolConfig(
                name="openai_tts",
                type="tts",
                primary=False,
                cost_per_use=0.015,
                fallback="chatterbox",
            ),
            ToolConfig(
                name="chatterbox",
                type="tts",
                primary=False,
                cost_per_use=0.0,  # Local
            ),
        ],
        "music": [
            ToolConfig(
                name="suno",
                type="music",
                primary=True,
                cost_per_use=0.05,
                fallback="mubert",
            ),
            ToolConfig(
                name="mubert",
                type="music",
                primary=False,
                cost_per_use=0.02,
                fallback="local_library",
            ),
            ToolConfig(
                name="local_library",
                type="music",
                primary=False,
                cost_per_use=0.0,
            ),
        ],
    }

    def __init__(
        self,
        tools: dict[str, list[ToolConfig]] | None = None,
        tool_health: dict[str, ToolHealth | str] | None = None,
    ):
        """
        Initialize tool selector.

        Args:
            tools: Custom tool configurations (overrides defaults)
            tool_health: Current health status of tools
        """
        self.tools = tools or self.DEFAULT_TOOLS
        self.tool_health: dict[str, ToolHealth] = {}

        if tool_health:
            for name, health in tool_health.items():
                if isinstance(health, str):
                    self.tool_health[name] = ToolHealth(health)
                else:
                    self.tool_health[name] = health

    def select_visual_tool(
        self,
        requirement: dict[str, Any] | AssetRequirement,
        max_cost: float | None = None,
    ) -> dict[str, Any]:
        """
        Select the best tool for a visual asset requirement.

        Args:
            requirement: Asset requirement (dict or AssetRequirement)
            max_cost: Maximum allowed cost for this operation

        Returns:
            Tool selection with name, type, cost, etc.
        """
        if isinstance(requirement, dict):
            visual_type = requirement.get("visual_type", "stock")
            if isinstance(visual_type, str):
                visual_type = VisualType(visual_type)
        else:
            visual_type = requirement.visual_type

        # Map visual type to tool category
        tool_category = self._get_tool_category_for_visual(visual_type)

        if tool_category is None:
            return {
                "name": "none",
                "type": "none",
                "cost": 0.0,
                "reason": "No tool needed for this visual type",
            }

        return self._select_best_tool(tool_category, max_cost)

    def _get_tool_category_for_visual(self, visual_type: VisualType) -> str | None:
        """Map visual type to tool category."""
        mapping = {
            VisualType.STOCK: "stock_video",
            VisualType.AI_GENERATED: "ai_image",
            VisualType.SCREEN_RECORDING: None,  # Special handling
            VisualType.BRAND_ASSET: None,  # Local assets
            VisualType.TEXT_OVERLAY: None,  # Generated locally
        }
        return mapping.get(visual_type)

    def select_audio_tool(
        self,
        audio_type: str,
        max_cost: float | None = None,
    ) -> dict[str, Any]:
        """
        Select the best tool for an audio asset.

        Args:
            audio_type: Type of audio ("tts", "music", "sfx")
            max_cost: Maximum allowed cost

        Returns:
            Tool selection
        """
        tool_category = audio_type if audio_type in self.tools else "tts"
        return self._select_best_tool(tool_category, max_cost)

    def _select_best_tool(
        self,
        category: str,
        max_cost: float | None = None,
    ) -> dict[str, Any]:
        """
        Select the best available tool from a category.

        Args:
            category: Tool category (e.g., "stock_video", "ai_image")
            max_cost: Maximum allowed cost

        Returns:
            Selected tool info
        """
        if category not in self.tools:
            return {
                "name": "unknown",
                "type": "unknown",
                "cost": 0.0,
                "error": f"Unknown tool category: {category}",
            }

        tools = self.tools[category]

        # Try tools in order (primary first, then fallbacks)
        for tool in tools:
            # Check health
            health = self.get_tool_health(tool.name)
            if health == ToolHealth.DOWN:
                continue

            # Check cost constraint
            if max_cost is not None and tool.cost_per_use > max_cost:
                continue

            return {
                "name": tool.name,
                "type": tool.type,
                "cost": tool.cost_per_use,
                "health": health.value,
                "fallback": tool.fallback,
            }

        # No suitable tool found
        return {
            "name": tools[0].name if tools else "none",
            "type": tools[0].type if tools else "none",
            "cost": 0.0,
            "error": "No healthy tool available within budget",
        }

    def get_tool_health(self, tool_name: str) -> ToolHealth:
        """
        Get current health status of a tool.

        Args:
            tool_name: Name of the tool

        Returns:
            ToolHealth status
        """
        health = self.tool_health.get(tool_name, ToolHealth.UNKNOWN)
        # Handle string values (e.g., from direct dict assignment in tests)
        if isinstance(health, str):
            try:
                return ToolHealth(health)
            except ValueError:
                return ToolHealth.UNKNOWN
        return health

    def set_tool_health(self, tool_name: str, health: ToolHealth | str) -> None:
        """
        Update health status of a tool.

        Args:
            tool_name: Name of the tool
            health: New health status
        """
        if isinstance(health, str):
            health = ToolHealth(health)
        self.tool_health[tool_name] = health

    def get_fallback(self, tool_name: str) -> str | None:
        """
        Get fallback tool for a given tool.

        Args:
            tool_name: Name of the primary tool

        Returns:
            Fallback tool name or None
        """
        for category_tools in self.tools.values():
            for tool in category_tools:
                if tool.name == tool_name:
                    return tool.fallback
        return None

    def select_for_requirement(
        self,
        requirement: AssetRequirement,
        budget_remaining: float | None = None,
    ) -> dict[str, Any]:
        """
        Select all tools needed for a requirement.

        Args:
            requirement: Complete asset requirement
            budget_remaining: Remaining budget

        Returns:
            Dict with visual_tool, audio_tool selections
        """
        result: dict[str, Any] = {}

        # Visual tool
        if requirement.visual_type not in [VisualType.BRAND_ASSET, VisualType.SCREEN_RECORDING]:
            result["visual_tool"] = self.select_visual_tool(
                requirement, max_cost=budget_remaining
            )
            if budget_remaining and "cost" in result["visual_tool"]:
                budget_remaining -= result["visual_tool"]["cost"]

        # Audio tool (TTS)
        if requirement.has_voiceover:
            result["audio_tool"] = self.select_audio_tool(
                "tts", max_cost=budget_remaining
            )

        return result

    def get_all_healthy_tools(self) -> list[str]:
        """Get list of all healthy tools."""
        healthy = []
        for category_tools in self.tools.values():
            for tool in category_tools:
                health = self.get_tool_health(tool.name)
                if health in [ToolHealth.HEALTHY, ToolHealth.UNKNOWN]:
                    healthy.append(tool.name)
        return list(set(healthy))

    def get_tools_by_category(self, category: str) -> list[ToolConfig]:
        """Get all tools in a category."""
        return self.tools.get(category, [])
