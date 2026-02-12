"""
Pexels stock media provider.

Uses the Pexels API to search and download free stock videos and images.
Cost: $0 (free)
"""

from pathlib import Path

import httpx

from src.providers.base import ProviderCapability, ProviderHealth, ProviderInfo
from src.providers.stock.protocol import StockRequest, StockResponse


class PexelsProvider:
    """Stock media provider using Pexels API."""

    def __init__(
        self,
        api_key: str,
        download_dir: str = "/tmp/creative_master/stock",
    ):
        """Initialize the Pexels provider.

        Args:
            api_key: Pexels API key
            download_dir: Directory for downloaded assets

        Raises:
            ValueError: If API key is empty
        """
        if not api_key or not api_key.strip():
            raise ValueError("Pexels API key is required")

        self._api_key = api_key
        self._download_dir = Path(download_dir)
        self._download_dir.mkdir(parents=True, exist_ok=True)
        self._http_client: httpx.AsyncClient | None = None
        self._info = ProviderInfo(
            name="pexels",
            capability=ProviderCapability.STOCK_ASSETS,
            health=ProviderHealth.UNKNOWN,
            cost_per_unit=0.0,  # Free!
            priority=1,  # Highest priority (free)
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
                base_url="https://api.pexels.com",
                headers={"Authorization": self._api_key},
                timeout=30.0,
            )
        return self._http_client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def health_check(self) -> ProviderHealth:
        """Check if the Pexels API is healthy.

        Returns:
            Provider health status
        """
        try:
            client = await self._get_client()
            response = await client.get("/videos/search", params={"query": "test", "per_page": 1})

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

    async def search(self, request: StockRequest) -> list[StockResponse]:
        """Search for stock assets.

        Args:
            request: Stock asset search request

        Returns:
            List of matching assets
        """
        client = await self._get_client()

        if request.asset_type == "video":
            return await self._search_videos(client, request)
        else:
            return await self._search_images(client, request)

    async def _search_videos(
        self,
        client: httpx.AsyncClient,
        request: StockRequest,
    ) -> list[StockResponse]:
        """Search for videos."""
        params = {
            "query": request.query,
            "per_page": request.limit,
        }

        if request.orientation:
            params["orientation"] = request.orientation

        response = await client.get("/videos/search", params=params)
        response.raise_for_status()
        data = response.json()

        results = []
        for video in data.get("videos", []):
            video_files = video.get("video_files", [])
            if not video_files:
                continue

            # Get best quality file
            best_file = self._select_best_video_file(video_files, request)
            if not best_file:
                continue

            results.append(StockResponse(
                asset_id=str(video.get("id")),
                asset_type="video",
                url=best_file.get("link"),
                width=best_file.get("width"),
                height=best_file.get("height"),
                duration=video.get("duration"),
                license="pexels_license",
                source="pexels",
                cost=0.0,
                provider=self._info.name,
            ))

        return results

    async def _search_images(
        self,
        client: httpx.AsyncClient,
        request: StockRequest,
    ) -> list[StockResponse]:
        """Search for images."""
        params = {
            "query": request.query,
            "per_page": request.limit,
        }

        if request.orientation:
            params["orientation"] = request.orientation

        response = await client.get("/v1/search", params=params)
        response.raise_for_status()
        data = response.json()

        results = []
        for photo in data.get("photos", []):
            src = photo.get("src", {})
            results.append(StockResponse(
                asset_id=str(photo.get("id")),
                asset_type="image",
                url=src.get("original"),
                width=photo.get("width"),
                height=photo.get("height"),
                license="pexels_license",
                source="pexels",
                cost=0.0,
                provider=self._info.name,
            ))

        return results

    def _select_best_video_file(
        self,
        video_files: list[dict],
        request: StockRequest,
    ) -> dict | None:
        """Select the best video file based on requirements."""
        candidates = video_files

        # Filter by minimum dimensions if specified
        if request.min_width:
            candidates = [f for f in candidates if f.get("width", 0) >= request.min_width]
        if request.min_height:
            candidates = [f for f in candidates if f.get("height", 0) >= request.min_height]

        if not candidates:
            candidates = video_files  # Fall back to all files

        # Prefer higher resolution
        candidates.sort(
            key=lambda f: (f.get("width", 0) * f.get("height", 0)),
            reverse=True,
        )

        return candidates[0] if candidates else None

    async def download(self, asset: StockResponse, output_path: str) -> str:
        """Download an asset to local storage.

        Args:
            asset: Asset to download
            output_path: Where to save the file

        Returns:
            Path to downloaded file
        """
        if not asset.url:
            raise ValueError("Asset has no URL")

        client = await self._get_client()

        async with client.stream("GET", asset.url) as response:
            response.raise_for_status()

            with open(output_path, "wb") as f:
                async for chunk in response.aiter_bytes(8192):
                    f.write(chunk)

        return output_path
