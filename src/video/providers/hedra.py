"""Hedra API talking head provider."""

import asyncio

import httpx

from ..talking_head import TalkingHeadResult

# Default timeout for generation polling (10 minutes)
_POLL_TIMEOUT = 600
_POLL_INTERVAL = 5


class HedraProvider:
    """Generates lip-synced talking head video using the Hedra API.

    Workflow:
        1. Upload character image as asset
        2. Upload audio (VO) as asset
        3. Create generation job with both asset IDs
        4. Poll until generation completes
        5. Download resulting video
    """

    BASE_URL = "https://api.hedra.com/web-app/public"
    MODEL_ID = "d1dd37a3-e39a-4854-a298-6510289f9cf2"

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self._api_key}

    async def generate(
        self,
        character_image_path: str,
        audio_path: str,
        output_path: str,
    ) -> TalkingHeadResult:
        """Generate a talking head video from character image + audio.

        Args:
            character_image_path: Path to character face image.
            audio_path: Path to voiceover audio file.
            output_path: Where to save the resulting video.

        Returns:
            TalkingHeadResult with video path and metadata.
        """
        image_asset_id = await self._upload_asset(character_image_path, "image")
        audio_asset_id = await self._upload_asset(audio_path, "audio")
        generation_id = await self._create_generation(image_asset_id, audio_asset_id)
        download_url = await self._poll_until_complete(generation_id)
        await self._download_video(download_url, output_path)

        return TalkingHeadResult(
            video_path=output_path,
            duration_seconds=0.0,  # determined by audio length
            character_id="",
            provider="hedra",
        )

    async def health_check(self) -> bool:
        """Check if Hedra API is reachable."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{self.BASE_URL}/models",
                    headers=self._headers(),
                )
                return resp.status_code == 200
        except Exception:
            return False

    async def _upload_asset(self, file_path: str, asset_type: str) -> str:
        """Upload a file to Hedra as an asset.

        Args:
            file_path: Local path to the file.
            asset_type: "image" or "audio".

        Returns:
            The asset ID string.
        """
        async with httpx.AsyncClient(timeout=60.0) as client:
            # Step 1: Create asset record
            create_resp = await client.post(
                f"{self.BASE_URL}/assets",
                headers=self._headers(),
                json={"name": file_path.rsplit("/", 1)[-1], "type": asset_type},
            )
            create_resp.raise_for_status()
            asset_id = create_resp.json()["id"]

            # Step 2: Upload file to the asset
            with open(file_path, "rb") as f:
                upload_resp = await client.post(
                    f"{self.BASE_URL}/assets/{asset_id}/upload",
                    headers=self._headers(),
                    files={"file": f},
                )
                upload_resp.raise_for_status()

        return asset_id

    async def _create_generation(self, image_id: str, audio_id: str) -> str:
        """Start a generation job.

        Args:
            image_id: Uploaded image asset ID.
            audio_id: Uploaded audio asset ID.

        Returns:
            The generation ID string.
        """
        payload = {
            "type": "video",
            "ai_model_id": self.MODEL_ID,
            "start_keyframe_id": image_id,
            "audio_id": audio_id,
            "generated_video_inputs": {
                "text_prompt": "",
                "resolution": "720p",
                "aspect_ratio": "9:16",
            },
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.BASE_URL}/generations",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()["id"]

    async def _poll_until_complete(
        self, generation_id: str, timeout: float = _POLL_TIMEOUT,
    ) -> str:
        """Poll generation status until complete.

        Args:
            generation_id: The generation ID to poll.
            timeout: Max seconds to wait.

        Returns:
            The download URL for the completed video.

        Raises:
            TimeoutError: If generation doesn't complete in time.
            RuntimeError: If generation fails.
        """
        elapsed = 0.0
        async with httpx.AsyncClient(timeout=30.0) as client:
            while elapsed < timeout:
                resp = await client.get(
                    f"{self.BASE_URL}/generations/{generation_id}/status",
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()
                status = data.get("status", "")

                if status == "complete":
                    return data["download_url"]
                if status == "failed":
                    msg = f"Generation {generation_id} failed: {data.get('error', 'unknown')}"
                    raise RuntimeError(msg)

                await asyncio.sleep(_POLL_INTERVAL)
                elapsed += _POLL_INTERVAL

        raise TimeoutError(f"Generation {generation_id} timed out after {timeout}s")

    async def _download_video(self, url: str, output_path: str) -> None:
        """Stream-download the generated video.

        Args:
            url: Download URL from Hedra.
            output_path: Local path to save the video.
        """
        async with httpx.AsyncClient(timeout=120.0) as client, client.stream("GET", url) as resp:
            resp.raise_for_status()
            with open(output_path, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=8192):
                    f.write(chunk)
