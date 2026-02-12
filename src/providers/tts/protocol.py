"""
TTS (Text-to-Speech) provider protocol.

Defines the common interface for TTS providers like ElevenLabs, Coqui, etc.
"""

from typing import Protocol

from pydantic import BaseModel, Field, field_validator

from src.providers.base import ProviderHealth, ProviderInfo


class TTSRequest(BaseModel):
    """Request for text-to-speech synthesis."""

    text: str = Field(..., min_length=1, description="Text to synthesize")
    voice_id: str | None = Field(
        default=None,
        description="Voice ID to use (provider default if None)",
    )
    stability: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Voice stability (0=variable, 1=stable)",
    )
    similarity_boost: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description="Voice similarity boost",
    )
    model_id: str | None = Field(
        default=None,
        description="Specific TTS model to use",
    )

    @field_validator("text")
    @classmethod
    def text_must_not_be_empty(cls, v: str) -> str:
        """Validate text is not empty."""
        if not v.strip():
            raise ValueError("Text cannot be empty")
        return v


class TTSResponse(BaseModel):
    """Response from text-to-speech synthesis."""

    audio_path: str = Field(..., description="Path to generated audio file")
    duration_seconds: float | None = Field(
        default=None,
        description="Duration of generated audio",
    )
    cost: float = Field(
        default=0.0,
        ge=0.0,
        description="Cost of generation",
    )
    provider: str | None = Field(
        default=None,
        description="Provider that generated the audio",
    )
    character_count: int | None = Field(
        default=None,
        description="Number of characters processed",
    )
    voice_id: str | None = Field(
        default=None,
        description="Voice ID that was used",
    )


class TTSProviderProtocol(Protocol):
    """Protocol for TTS providers."""

    @property
    def info(self) -> ProviderInfo:
        """Get provider information."""
        ...

    async def health_check(self) -> ProviderHealth:
        """Check if the provider is healthy."""
        ...

    async def synthesize(self, request: TTSRequest) -> TTSResponse:
        """Synthesize speech from text.

        Args:
            request: TTS synthesis request

        Returns:
            Generated audio response
        """
        ...
