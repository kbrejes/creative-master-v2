"""
LLM provider protocol.

Defines the common interface for LLM providers like Anthropic Claude,
OpenAI GPT, Ollama, etc.
"""

from typing import Literal, Protocol

from pydantic import BaseModel, Field, field_validator

from src.providers.providers.base import ProviderHealth, ProviderInfo


class Message(BaseModel):
    """A message in a conversation."""

    role: Literal["user", "assistant", "system"] = Field(
        ..., description="The role of the message sender"
    )
    content: str = Field(default="", description="The message content")


class LLMRequest(BaseModel):
    """Request for LLM completion."""

    messages: list[Message] = Field(
        ..., min_length=1, description="Conversation messages"
    )
    system: str | None = Field(
        default=None,
        description="System prompt/instructions",
    )
    model: str | None = Field(
        default=None,
        description="Specific model to use (provider default if None)",
    )
    max_tokens: int = Field(
        default=1024,
        ge=1,
        le=100000,
        description="Maximum tokens to generate",
    )
    temperature: float = Field(
        default=1.0,
        ge=0.0,
        le=2.0,
        description="Sampling temperature",
    )
    stop_sequences: list[str] | None = Field(
        default=None,
        description="Sequences that stop generation",
    )

    @field_validator("messages")
    @classmethod
    def messages_must_not_be_empty(cls, v: list[Message]) -> list[Message]:
        """Validate that messages list is not empty."""
        if not v:
            raise ValueError("At least one message is required")
        return v


class LLMResponse(BaseModel):
    """Response from LLM completion."""

    content: str = Field(..., description="Generated text content")
    input_tokens: int | None = Field(
        default=None,
        description="Number of input tokens",
    )
    output_tokens: int | None = Field(
        default=None,
        description="Number of output tokens",
    )
    cost: float = Field(
        default=0.0,
        ge=0.0,
        description="Cost of this completion",
    )
    model: str | None = Field(
        default=None,
        description="Model that generated the response",
    )
    provider: str | None = Field(
        default=None,
        description="Provider that generated the response",
    )
    finish_reason: str | None = Field(
        default=None,
        description="Why generation stopped",
    )

    @property
    def total_tokens(self) -> int:
        """Get total token count."""
        input_count = self.input_tokens or 0
        output_count = self.output_tokens or 0
        return input_count + output_count


class LLMProviderProtocol(Protocol):
    """Protocol for LLM providers."""

    @property
    def info(self) -> ProviderInfo:
        """Get provider information."""
        ...

    async def health_check(self) -> ProviderHealth:
        """Check if the provider is healthy."""
        ...

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Generate a completion.

        Args:
            request: LLM completion request

        Returns:
            Generated response
        """
        ...
