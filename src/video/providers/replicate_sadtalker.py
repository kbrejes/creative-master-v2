"""Replicate SadTalker talking head provider."""

import os

import httpx

from ..talking_head import TalkingHeadResult


class ReplicateSadTalkerProvider:
    """Generates lip-synced talking head video using SadTalker on Replicate.

    Uses the cjwbw/sadtalker model via the Replicate Python SDK.
    Free tier available — no subscription required.
    """

    MODEL = "cjwbw/sadtalker"

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

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
        if self._api_key:
            os.environ["REPLICATE_API_TOKEN"] = self._api_key

        import replicate

        # Community models need explicit version for SDK v1.x
        ref = await self._resolve_model_ref()

        with open(character_image_path, "rb") as img_fh, \
             open(audio_path, "rb") as aud_fh:
            output_url = await replicate.async_run(
                ref,
                input={
                    "source_image": img_fh,
                    "driven_audio": aud_fh,
                    "still_mode": True,
                    "use_enhancer": False,
                    "preprocess": "crop",
                    "size_of_image": 256,
                },
            )

        await self._download_output(str(output_url), output_path)

        return TalkingHeadResult(
            video_path=output_path,
            duration_seconds=0.0,
            character_id="",
            provider="replicate",
        )

    async def health_check(self) -> bool:
        """Check if SadTalker model is accessible on Replicate."""
        if self._api_key:
            os.environ["REPLICATE_API_TOKEN"] = self._api_key

        try:
            import replicate

            await replicate.models.async_get(self.MODEL)
            return True
        except Exception:
            return False

    async def _resolve_model_ref(self) -> str:
        """Resolve full model ref with version hash.

        Community models on Replicate need 'owner/name:version' format.
        Caches the version after first lookup.

        Returns:
            Model ref string like 'cjwbw/sadtalker:a519cc0c...'.
        """
        if not hasattr(self, "_cached_ref"):
            import replicate

            model = await replicate.models.async_get(self.MODEL)
            if model.latest_version:
                self._cached_ref = f"{self.MODEL}:{model.latest_version.id}"
            else:
                self._cached_ref = self.MODEL
        return self._cached_ref

    async def _download_output(self, url: str, output_path: str) -> None:
        """Download the generated video from Replicate CDN.

        Args:
            url: Output URL from Replicate.
            output_path: Local path to save the video.
        """
        async with httpx.AsyncClient(timeout=120.0) as client, client.stream("GET", url) as resp:
            resp.raise_for_status()
            with open(output_path, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=8192):
                    f.write(chunk)
