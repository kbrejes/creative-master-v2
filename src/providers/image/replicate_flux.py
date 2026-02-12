"""
Replicate Flux image generation provider.

Uses the Replicate API to generate images with the Flux model.
Cost: ~$0.01 per image.
"""

import asyncio
from typing import Any

import httpx

from src.providers.providers.base import ProviderCapability, ProviderHealth, ProviderInfo
from src.providers.providers.image.protocol import ImageRequest, ImageResponse


class ReplicateFluxProvider:
    """Image generation provider using Replicate's Flux model."""

    # Flux model on Replicate
    MODEL_VERSION = "black-forest-labs/flux-schnell"

    def __init__(self, api_token: str):
        """Initialize the Replicate Flux provider.

        Args:
            api_token: Replicate API token

        Raises:
            ValueError: If API token is empty
        """
        if not api_token or not api_token.strip():
            raise ValueError("Replicate API token is required")

        self._api_token = api_token
        self._http_client: httpx.AsyncClient | None = None
        self._info = ProviderInfo(
            name="replicate_flux",
            capability=ProviderCapability.IMAGE_GENERATION,
            health=ProviderHealth.UNKNOWN,
            cost_per_unit=0.01,  # ~$0.01 per image
            priority=10,  # Prefer this provider (cheap)
            is_local=False,
        )

    @property
    def info(self) -> ProviderInfo:
        """Get provider information."""
        return self._info

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                base_url="https://api.replicate.com/v1",
                headers={
                    "Authorization": f"Bearer {self._api_token}",
                    "Content-Type": "application/json",
                },
                timeout=120.0,  # Replicate can be slow
            )
        return self._http_client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def health_check(self) -> ProviderHealth:
        """Check if Replicate API is healthy.

        Returns:
            Provider health status
        """
        try:
            client = await self._get_client()
            response = await client.get("/models")

            if response.status_code == 200:
                self._info.health = ProviderHealth.HEALTHY
                return ProviderHealth.HEALTHY
            elif response.status_code == 429:  # Rate limited
                self._info.health = ProviderHealth.DEGRADED
                return ProviderHealth.DEGRADED
            else:
                self._info.health = ProviderHealth.UNHEALTHY
                return ProviderHealth.UNHEALTHY

        except Exception:
            self._info.health = ProviderHealth.UNHEALTHY
            return ProviderHealth.UNHEALTHY

    async def generate(self, request: ImageRequest) -> ImageResponse:
        """Generate an image using Flux.

        Args:
            request: Image generation request

        Returns:
            Generated image response

        Raises:
            Exception: If generation fails
        """
        # Build input parameters for Flux
        input_params: dict[str, Any] = {
            "prompt": request.prompt,
            "width": request.width,
            "height": request.height,
        }

        if request.negative_prompt:
            input_params["negative_prompt"] = request.negative_prompt

        if request.seed is not None:
            input_params["seed"] = request.seed

        # Run the prediction
        result = await self._run_prediction(input_params)

        # Extract output URL
        output = result.get("output", [])
        image_url = output[0] if output else None

        if not image_url:
            raise Exception("No image URL in response")

        return ImageResponse(
            image_url=image_url,
            width=request.width,
            height=request.height,
            cost=self._info.cost_per_unit,
            provider=self._info.name,
        )

    async def _run_prediction(self, input_params: dict[str, Any]) -> dict[str, Any]:
        """Run a prediction on Replicate.

        Args:
            input_params: Model input parameters

        Returns:
            Prediction result

        Raises:
            Exception: If prediction fails
        """
        client = await self._get_client()

        # Create prediction
        create_response = await client.post(
            "/predictions",
            json={
                "version": self.MODEL_VERSION,
                "input": input_params,
            },
        )
        create_response.raise_for_status()
        prediction = create_response.json()

        # Poll for completion
        prediction_id = prediction["id"]
        max_attempts = 60  # 60 * 2s = 2 minutes max
        attempt = 0

        while attempt < max_attempts:
            poll_response = await client.get(f"/predictions/{prediction_id}")
            poll_response.raise_for_status()
            prediction = poll_response.json()

            status = prediction.get("status")
            if status == "succeeded":
                return prediction
            elif status in ("failed", "canceled"):
                error = prediction.get("error", "Unknown error")
                raise Exception(f"Prediction failed: {error}")

            await asyncio.sleep(2)
            attempt += 1

        raise Exception("Prediction timed out")
