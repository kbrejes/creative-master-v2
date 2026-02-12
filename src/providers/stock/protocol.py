"""
Stock asset provider protocol.

Defines the common interface for stock media providers like Pexels, Pixabay, etc.
"""

from typing import Literal, Protocol

from pydantic import BaseModel, Field, field_validator

from src.providers.providers.base import ProviderHealth, ProviderInfo


class StockRequest(BaseModel):
    """Request for stock asset search."""

    query: str = Field(..., min_length=1, description="Search query")
    asset_type: Literal["video", "image"] = Field(
        default="video",
        description="Type of asset to search for",
    )
    orientation: Literal["portrait", "landscape", "square"] | None = Field(
        default=None,
        description="Preferred orientation",
    )
    min_duration: int | None = Field(
        default=None,
        ge=1,
        description="Minimum duration in seconds (video only)",
    )
    min_width: int | None = Field(
        default=None,
        ge=1,
        description="Minimum width in pixels",
    )
    min_height: int | None = Field(
        default=None,
        ge=1,
        description="Minimum height in pixels",
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum results to return",
    )

    @field_validator("query")
    @classmethod
    def query_must_not_be_empty(cls, v: str) -> str:
        """Validate query is not empty."""
        if not v.strip():
            raise ValueError("Query cannot be empty")
        return v


class StockResponse(BaseModel):
    """Response from stock asset search and download."""

    asset_id: str = Field(..., description="Unique asset ID")
    local_path: str | None = Field(
        default=None,
        description="Path to downloaded file",
    )
    url: str | None = Field(
        default=None,
        description="URL of the asset",
    )
    asset_type: Literal["video", "image"] = Field(
        ..., description="Type of asset"
    )
    width: int | None = Field(default=None, description="Width in pixels")
    height: int | None = Field(default=None, description="Height in pixels")
    duration: int | None = Field(
        default=None,
        description="Duration in seconds (video only)",
    )
    license: str = Field(
        default="unknown",
        description="License type",
    )
    source: str | None = Field(
        default=None,
        description="Source platform (pexels, pixabay, etc.)",
    )
    cost: float = Field(
        default=0.0,
        ge=0.0,
        description="Cost of the asset (usually free)",
    )
    provider: str | None = Field(
        default=None,
        description="Provider that found the asset",
    )


class StockProviderProtocol(Protocol):
    """Protocol for stock asset providers."""

    @property
    def info(self) -> ProviderInfo:
        """Get provider information."""
        ...

    async def health_check(self) -> ProviderHealth:
        """Check if the provider is healthy."""
        ...

    async def search(self, request: StockRequest) -> list[StockResponse]:
        """Search for stock assets.

        Args:
            request: Stock asset search request

        Returns:
            List of matching assets
        """
        ...

    async def download(self, asset: StockResponse, output_path: str) -> str:
        """Download an asset to local storage.

        Args:
            asset: Asset to download
            output_path: Where to save the file

        Returns:
            Path to downloaded file
        """
        ...
