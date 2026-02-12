"""
Ollama LLM provider.

Uses local Ollama server for free LLM inference.
Cost: $0 (runs locally)
"""

from typing import Any

import httpx

from src.providers.base import ProviderCapability, ProviderHealth, ProviderInfo
from src.providers.llm.protocol import LLMRequest, LLMResponse


class OllamaProvider:
    """LLM provider using local Ollama server."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        default_model: str = "llama3.2",
    ):
        """Initialize the Ollama provider.

        Args:
            base_url: Ollama server URL
            default_model: Default model to use
        """
        self._base_url = base_url
        self._default_model = default_model
        self._http_client: httpx.AsyncClient | None = None
        self._info = ProviderInfo(
            name="ollama",
            capability=ProviderCapability.LLM,
            health=ProviderHealth.UNKNOWN,
            cost_per_unit=0.0,  # Free!
            priority=1,  # Highest priority (cheapest)
            is_local=True,
        )

    @property
    def info(self) -> ProviderInfo:
        """Get provider information."""
        return self._info

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=120.0,  # LLMs can be slow
            )
        return self._http_client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def health_check(self) -> ProviderHealth:
        """Check if the Ollama server is healthy.

        Returns:
            Provider health status
        """
        try:
            client = await self._get_client()
            response = await client.get("/api/tags")

            if response.status_code == 200:
                self._info.health = ProviderHealth.HEALTHY
                return ProviderHealth.HEALTHY
            else:
                self._info.health = ProviderHealth.UNHEALTHY
                return ProviderHealth.UNHEALTHY

        except Exception:
            self._info.health = ProviderHealth.UNHEALTHY
            return ProviderHealth.UNHEALTHY

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Generate a completion using Ollama.

        Args:
            request: LLM completion request

        Returns:
            Generated response
        """
        model = request.model or self._default_model

        # Build messages list
        messages: list[dict[str, Any]] = []

        # Add system message if provided
        if request.system:
            messages.append({
                "role": "system",
                "content": request.system,
            })

        # Add conversation messages
        for msg in request.messages:
            messages.append({
                "role": msg.role,
                "content": msg.content,
            })

        # Build request payload
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,  # Non-streaming for simplicity
            "options": {
                "temperature": request.temperature,
            },
        }

        # Make API call
        client = await self._get_client()
        response = await client.post(
            "/api/chat",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

        # Extract response
        message = data.get("message", {})
        content = message.get("content", "")

        # Token counts
        input_tokens = data.get("prompt_eval_count", 0)
        output_tokens = data.get("eval_count", 0)

        return LLMResponse(
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=0.0,  # Always free
            model=data.get("model", model),
            provider=self._info.name,
            finish_reason="stop" if data.get("done") else None,
        )
