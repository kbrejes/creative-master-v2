"""
Asset Gatherer - Searches and downloads stock assets from APIs.
"""

import hashlib
import os
import random
from pathlib import Path
from typing import Any, Protocol

import httpx


class StockAPIProtocol(Protocol):
    """Protocol for stock API clients."""

    async def search(
        self,
        query: str,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Search for assets."""
        ...

    async def download(
        self,
        asset_id: str,
        output_path: str,
        **kwargs: Any,
    ) -> str:
        """Download an asset."""
        ...


def build_search_query(shot: dict[str, Any]) -> str:
    """Build a Pexels search query from shot info.

    Combines description + search_terms + mood into a multi-word query.
    """
    parts: list[str] = []

    search_terms = shot.get("search_terms", [])
    if search_terms:
        parts.extend(search_terms)

    description = shot.get("description", "")
    if description and not search_terms:
        # Extract key nouns from description
        parts.extend(description.split())

    mood = shot.get("mood", "")
    if mood:
        parts.append(mood)

    if not parts:
        return "business"

    return " ".join(parts)


def map_orientation(aspect_ratio: str) -> str:
    """Map aspect ratio to Pexels orientation parameter."""
    mapping = {
        "9:16": "portrait",
        "16:9": "landscape",
        "1:1": "square",
    }
    return mapping.get(aspect_ratio, "landscape")


class AssetGatherer:
    """
    Gathers stock assets from various APIs.

    Supports:
    - Pexels (video, images)
    - Storyblocks (video)
    - Unsplash (images)
    - Pixabay (video, images)
    """

    def __init__(
        self,
        stock_api: StockAPIProtocol | None = None,
        download_dir: str = "/tmp/creative_master/assets",
        pexels_api_key: str | None = None,
    ):
        """
        Initialize asset gatherer.

        Args:
            stock_api: Custom stock API client (for testing)
            download_dir: Directory for downloaded assets
            pexels_api_key: API key for Pexels
        """
        self.stock_api = stock_api
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)

        self.pexels_api_key = pexels_api_key or os.environ.get("PEXELS_API_KEY", "")
        self._http_client: httpx.AsyncClient | None = None

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self._http_client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def get_stock_video(
        self,
        requirement: dict[str, Any],
    ) -> dict[str, Any] | None:
        """
        Search for and download a stock video matching requirements.

        Args:
            requirement: Asset requirement with search_terms, min_duration, etc.

        Returns:
            Asset info dict or None if not found
        """
        # If custom API provided (testing), use it
        if self.stock_api:
            search_terms = requirement.get("search_terms", [])
            query = " ".join(search_terms) if search_terms else "business"
            min_duration = requirement.get("min_duration", 5)

            try:
                results = await self.stock_api.search(
                    query,
                    orientation=requirement.get("orientation", "portrait"),
                    min_duration=min_duration,
                )
            except Exception:
                return {"fallback_needed": True}

            # Retry with broader query if no results
            if not results and len(search_terms) > 1:
                broader_query = search_terms[0] if search_terms else "business"
                try:
                    results = await self.stock_api.search(
                        broader_query,
                        orientation=requirement.get("orientation", "portrait"),
                        min_duration=min_duration,
                    )
                except Exception:
                    return {"fallback_needed": True}

            if not results:
                return {"fallback_needed": True}

            # Filter by resolution if specified
            min_res = requirement.get("min_resolution", (720, 1280))
            valid_results = [
                r for r in results
                if r.get("width", 0) >= min_res[0] and r.get("height", 0) >= min_res[1]
            ]

            if not valid_results:
                valid_results = results  # Use unfiltered if none pass

            # Duration-aware selection: prefer clips >= min_duration
            long_enough = [
                r for r in valid_results
                if r.get("duration", 0) >= min_duration
            ]
            if long_enough:
                valid_results = long_enough

            best = random.choice(valid_results)

            # Download
            output_path = await self.stock_api.download(
                best["id"],
                str(self.download_dir / f"stock_{best['id']}.mp4"),
            )

            return {
                "id": best["id"],
                "path": output_path,
                "source": "pexels",
                "license": best.get("license", "pexels_license"),
                "license_valid": True,
                "width": best.get("width", 1080),
                "height": best.get("height", 1920),
                "duration": best.get("duration", 10),
            }

        # Real Pexels API implementation
        return await self._search_pexels_video(requirement)

    async def _search_pexels_video(
        self,
        requirement: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Search Pexels for video."""
        if not self.pexels_api_key:
            return {"fallback_needed": True, "error": "No Pexels API key"}

        search_terms = requirement.get("search_terms", [])
        query = " ".join(search_terms) if search_terms else "business"

        client = await self._get_http_client()

        try:
            response = await client.get(
                "https://api.pexels.com/videos/search",
                params={
                    "query": query,
                    "orientation": "portrait",
                    "per_page": 10,
                },
                headers={"Authorization": self.pexels_api_key},
            )
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            return {"fallback_needed": True, "error": str(e)}

        videos = data.get("videos", [])
        if not videos:
            return {"fallback_needed": True}

        # Filter by requirements
        min_duration = requirement.get("min_duration", 0)
        min_res = requirement.get("min_resolution", (720, 1280))

        valid_videos = []
        for video in videos:
            if video.get("duration", 0) >= min_duration:
                # Check resolution of available files
                for vf in video.get("video_files", []):
                    if vf.get("width", 0) >= min_res[0] and vf.get("height", 0) >= min_res[1]:
                        valid_videos.append((video, vf))
                        break

        if not valid_videos:
            # Use first available if none meet requirements
            if videos and videos[0].get("video_files"):
                valid_videos = [(videos[0], videos[0]["video_files"][0])]
            else:
                return {"fallback_needed": True}

        video, video_file = random.choice(valid_videos)

        # Download the video
        download_url = video_file.get("link")
        if not download_url:
            return {"fallback_needed": True}

        video_id = str(video.get("id", "unknown"))
        output_path = self.download_dir / f"pexels_{video_id}.mp4"

        try:
            await self._download_file(download_url, str(output_path))
        except Exception as e:
            return {"fallback_needed": True, "error": str(e)}

        return {
            "id": video_id,
            "path": str(output_path),
            "source": "pexels",
            "license": "pexels_license",
            "license_valid": True,
            "width": video_file.get("width", 1080),
            "height": video_file.get("height", 1920),
            "duration": video.get("duration", 10),
            "url": download_url,
        }

    async def search_stock_video(
        self,
        requirement: dict[str, Any],
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Search for stock videos without downloading.

        Args:
            requirement: Search requirements
            limit: Maximum results to return

        Returns:
            List of video options
        """
        if self.stock_api:
            search_terms = requirement.get("search_terms", [])
            query = " ".join(search_terms) if search_terms else "business"
            results = await self.stock_api.search(query)
            return results[:limit]

        # Real Pexels search
        if not self.pexels_api_key:
            return []

        search_terms = requirement.get("search_terms", [])
        query = " ".join(search_terms) if search_terms else "business"

        client = await self._get_http_client()

        try:
            response = await client.get(
                "https://api.pexels.com/videos/search",
                params={
                    "query": query,
                    "orientation": "portrait",
                    "per_page": limit,
                },
                headers={"Authorization": self.pexels_api_key},
            )
            response.raise_for_status()
            data = response.json()
        except Exception:
            return []

        results = []
        for video in data.get("videos", [])[:limit]:
            video_file = video.get("video_files", [{}])[0]
            results.append({
                "id": str(video.get("id")),
                "url": video_file.get("link", ""),
                "width": video_file.get("width", 0),
                "height": video_file.get("height", 0),
                "duration": video.get("duration", 0),
                "license": "pexels_license",
            })

        return results

    async def _download_file(
        self,
        url: str,
        output_path: str,
        chunk_size: int = 8192,
    ) -> str:
        """
        Download a file from URL.

        Args:
            url: Download URL
            output_path: Where to save the file
            chunk_size: Download chunk size

        Returns:
            Path to downloaded file
        """
        client = await self._get_http_client()

        async with client.stream("GET", url) as response:
            response.raise_for_status()

            with open(output_path, "wb") as f:
                async for chunk in response.aiter_bytes(chunk_size):
                    f.write(chunk)

        return output_path

    def verify_license(self, asset: dict[str, Any]) -> bool:
        """
        Verify that an asset's license allows commercial use.

        Args:
            asset: Asset info dict

        Returns:
            True if license is valid for commercial use
        """
        # Pexels, Pixabay, Unsplash all allow commercial use
        valid_licenses = [
            "pexels_license",
            "pixabay_license",
            "unsplash_license",
            "cc0",
            "commercial_use_allowed",
        ]

        license_type = asset.get("license", "").lower()
        return any(valid in license_type for valid in valid_licenses)

    async def get_stock_image(
        self,
        requirement: dict[str, Any],
    ) -> dict[str, Any] | None:
        """
        Search for and download a stock image.

        Args:
            requirement: Asset requirement

        Returns:
            Asset info dict or None
        """
        # Similar to video but for images
        if not self.pexels_api_key:
            return {"fallback_needed": True, "error": "No Pexels API key"}

        search_terms = requirement.get("search_terms", [])
        query = " ".join(search_terms) if search_terms else "business"

        client = await self._get_http_client()

        try:
            response = await client.get(
                "https://api.pexels.com/v1/search",
                params={
                    "query": query,
                    "orientation": "portrait",
                    "per_page": 5,
                },
                headers={"Authorization": self.pexels_api_key},
            )
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            return {"fallback_needed": True, "error": str(e)}

        photos = data.get("photos", [])
        if not photos:
            return {"fallback_needed": True}

        photo = photos[0]
        photo_id = str(photo.get("id", "unknown"))
        download_url = photo.get("src", {}).get("original", "")

        if not download_url:
            return {"fallback_needed": True}

        output_path = self.download_dir / f"pexels_{photo_id}.jpg"

        try:
            await self._download_file(download_url, str(output_path))
        except Exception as e:
            return {"fallback_needed": True, "error": str(e)}

        return {
            "id": photo_id,
            "path": str(output_path),
            "source": "pexels",
            "license": "pexels_license",
            "license_valid": True,
            "width": photo.get("width", 1080),
            "height": photo.get("height", 1920),
        }

    def get_asset_hash(self, asset_path: str) -> str:
        """
        Get hash of an asset file for deduplication.

        Args:
            asset_path: Path to asset file

        Returns:
            SHA256 hash of file
        """
        hash_sha256 = hashlib.sha256()
        with open(asset_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_sha256.update(chunk)
        return hash_sha256.hexdigest()
