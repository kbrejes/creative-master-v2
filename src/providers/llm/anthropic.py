"""
Anthropic Claude LLM provider.

Uses the Anthropic API to access Claude models.
"""

from typing import Any

import anthropic

from src.providers.base import ProviderCapability, ProviderHealth, ProviderInfo
from src.providers.llm.protocol import LLMRequest, LLMResponse

# Pricing per 1K tokens (as of late 2024)
PRICING = {
    "claude-3-5-sonnet-20241022": {"input": 0.003, "output": 0.015},
    "claude-3-opus-20240229": {"input": 0.015, "output": 0.075},
    "claude-3-sonnet-20240229": {"input": 0.003, "output": 0.015},
    "claude-3-haiku-20240307": {"input": 0.00025, "output": 0.00125},
}


class AnthropicProvider:
    """LLM provider using Anthropic's Claude API."""

    def __init__(
        self,
        api_key: str,
        default_model: str = "claude-3-5-sonnet-20241022",
    ):
        """Initialize the Anthropic provider.

        Args:
            api_key: Anthropic API key
            default_model: Default model to use

        Raises:
            ValueError: If API key is empty
        """
        if not api_key or not api_key.strip():
            raise ValueError("Anthropic API key is required")

        self._api_key = api_key
        self._default_model = default_model
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._info = ProviderInfo(
            name="anthropic",
            capability=ProviderCapability.LLM,
            health=ProviderHealth.UNKNOWN,
            cost_per_unit=0.003,  # Base rate for input tokens per 1K
            priority=50,  # Mid-tier priority
            is_local=False,
        )

    @property
    def info(self) -> ProviderInfo:
        """Get provider information."""
        return self._info

    async def health_check(self) -> ProviderHealth:
        """Check if the Anthropic API is healthy.

        Returns:
            Provider health status
        """
        try:
            # Simple test message to verify API connectivity
            await self._client.messages.create(
                model=self._default_model,
                max_tokens=5,
                messages=[{"role": "user", "content": "hi"}],
            )
            self._info.health = ProviderHealth.HEALTHY
            return ProviderHealth.HEALTHY
        except anthropic.RateLimitError:
            self._info.health = ProviderHealth.DEGRADED
            return ProviderHealth.DEGRADED
        except Exception:
            self._info.health = ProviderHealth.UNHEALTHY
            return ProviderHealth.UNHEALTHY

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Generate a completion using Claude.

        Args:
            request: LLM completion request

        Returns:
            Generated response
        """
        model = request.model or self._default_model

        # Convert messages to Anthropic format
        messages: list[dict[str, Any]] = []
        for msg in request.messages:
            if msg.role in ("user", "assistant"):
                messages.append({
                    "role": msg.role,
                    "content": msg.content,
                })

        # Build request kwargs
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": request.max_tokens,
            "messages": messages,
        }

        if request.system:
            kwargs["system"] = request.system

        if request.temperature != 1.0:
            kwargs["temperature"] = request.temperature

        if request.stop_sequences:
            kwargs["stop_sequences"] = request.stop_sequences

        # Make API call
        response = await self._client.messages.create(**kwargs)

        # Extract response content
        content = ""
        if response.content:
            content = response.content[0].text

        # Calculate cost
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        cost = self._calculate_cost(model, input_tokens, output_tokens)

        return LLMResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            model=response.model,
            provider=self._info.name,
            finish_reason=response.stop_reason,
        )

    def _calculate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Calculate cost for a completion.

        Args:
            model: Model name
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens

        Returns:
            Estimated cost in USD
        """
        pricing = PRICING.get(model, PRICING["claude-3-5-sonnet-20241022"])
        input_cost = (input_tokens / 1000) * pricing["input"]
        output_cost = (output_tokens / 1000) * pricing["output"]
        return input_cost + output_cost
