"""
Base abstractions for the provider layer.

Defines the core protocols and models used across all provider types.
"""

from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field, field_validator


class ProviderCapability(StrEnum):
    """Capabilities that providers can offer."""

    LLM = "llm"
    IMAGE_GENERATION = "image_generation"
    TTS = "tts"
    STOCK_ASSETS = "stock_assets"


class ProviderHealth(StrEnum):
    """Health status of a provider."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class ProviderInfo(BaseModel):
    """Information about a provider."""

    name: str = Field(..., min_length=1, description="Unique provider name")
    capability: ProviderCapability = Field(..., description="What this provider does")
    health: ProviderHealth = Field(
        default=ProviderHealth.UNKNOWN,
        description="Current health status",
    )
    cost_per_unit: float = Field(
        default=0.0,
        ge=0.0,
        description="Cost per unit (e.g., per image, per 1K tokens)",
    )
    priority: int = Field(
        default=100,
        description="Selection priority (lower = higher priority)",
    )
    is_local: bool = Field(
        default=False,
        description="Whether this provider runs locally",
    )

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        """Validate that name is not empty or whitespace."""
        if not v.strip():
            raise ValueError("Provider name cannot be empty")
        return v


@runtime_checkable
class ProviderProtocol(Protocol):
    """Protocol that all providers must implement."""

    @property
    def info(self) -> ProviderInfo:
        """Get provider information."""
        ...

    async def health_check(self) -> ProviderHealth:
        """Check if the provider is healthy and accessible."""
        ...
