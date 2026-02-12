"""
Image generation provider protocol.

Defines the common interface for image generation providers like DALL-E,
Replicate Flux, Stable Diffusion, etc.
"""

from typing import Literal, Protocol

from pydantic import BaseModel, Field, field_validator

from src.providers.providers.base import ProviderHealth, ProviderInfo


class ImageRequest(BaseModel):
    """Request for image generation."""

    prompt: str = Field(..., min_length=1, description="Image generation prompt")
    negative_prompt: str | None = Field(
        default=None,
        description="What to avoid in the image",
    )
    width: int = Field(default=1024, ge=64, le=4096, description="Image width")
    height: int = Field(default=1024, ge=64, le=4096, description="Image height")
    quality: Literal["standard", "hd"] = Field(
        default="standard",
        description="Quality level",
    )
    seed: int | None = Field(
        default=None,
        description="Seed for reproducible generation",
    )

    @field_validator("prompt")
    @classmethod
    def prompt_must_not_be_empty(cls, v: str) -> str:
        """Validate prompt is not empty."""
        if not v.strip():
            raise ValueError("Prompt cannot be empty")
        return v


class ImageResponse(BaseModel):
    """Response from image generation."""

    image_url: str | None = Field(
        default=None,
        description="URL of the generated image",
    )
    local_path: str | None = Field(
        default=None,
        description="Local path to downloaded image",
    )
    width: int | None = Field(
        default=None,
        description="Width of generated image",
    )
    height: int | None = Field(
        default=None,
        description="Height of generated image",
    )
    revised_prompt: str | None = Field(
        default=None,
        description="Provider's revised prompt (if modified)",
    )
    cost: float = Field(
        default=0.0,
        ge=0.0,
        description="Cost of generation",
    )
    provider: str | None = Field(
        default=None,
        description="Name of the provider that generated the image",
    )


class ImageProviderProtocol(Protocol):
    """Protocol for image generation providers."""

    @property
    def info(self) -> ProviderInfo:
        """Get provider information."""
        ...

    async def health_check(self) -> ProviderHealth:
        """Check if the provider is healthy."""
        ...

    async def generate(self, request: ImageRequest) -> ImageResponse:
        """Generate an image.

        Args:
            request: Image generation request

        Returns:
            Generated image response
        """
        ...
