"""
Asset Generator - Generates assets via AI (images, video, TTS).
"""

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any, Protocol

import httpx


class TTSAPIProtocol(Protocol):
    """Protocol for TTS API clients."""

    async def synthesize(
        self,
        text: str,
        voice_id: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Synthesize speech from text."""
        ...


class AssetGenerator:
    """
    Generates assets using AI services.

    Supports:
    - DALL-E 3 (images)
    - Runway ML (video)
    - ElevenLabs (TTS)
    - Suno (music)
    """

    def __init__(
        self,
        tts_api: TTSAPIProtocol | None = None,
        output_dir: str = "/tmp/creative_master/generated",
        openai_api_key: str | None = None,
        elevenlabs_api_key: str | None = None,
    ):
        """
        Initialize asset generator.

        Args:
            tts_api: Custom TTS API client (for testing)
            output_dir: Directory for generated assets
            openai_api_key: API key for OpenAI (DALL-E)
            elevenlabs_api_key: API key for ElevenLabs
        """
        self.tts_api = tts_api
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.openai_api_key = openai_api_key or os.environ.get("OPENAI_API_KEY", "")
        self.elevenlabs_api_key = elevenlabs_api_key or os.environ.get("ELEVENLABS_API_KEY", "")

        self._http_client: httpx.AsyncClient | None = None

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=60.0)
        return self._http_client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def generate_image(
        self,
        prompt: str,
        size: str = "1024x1792",
        quality: str = "hd",
        style: str = "natural",
        max_retries: int = 3,
        quality_requirements: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Generate an image using DALL-E 3.

        Args:
            prompt: Image generation prompt
            size: Image size (1024x1024, 1024x1792, 1792x1024)
            quality: Quality level (standard, hd)
            style: Style (vivid, natural)
            max_retries: Maximum retry attempts
            quality_requirements: Optional quality requirements

        Returns:
            Generated image info
        """
        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                result = await self._call_dalle(prompt, size, quality, style)

                # Download the image
                image_id = str(uuid.uuid4())[:8]
                output_path = self.output_dir / f"dalle_{image_id}.png"

                await self._download_image(result["image_url"], str(output_path))

                # Parse dimensions from size
                width, height = map(int, size.split("x"))

                response = {
                    "path": str(output_path),
                    "type": "ai_image",
                    "tool": "dalle",
                    "prompt": result.get("revised_prompt", prompt),
                    "cost": result.get("cost", 0.04),
                    "width": width,
                    "height": height,
                }

                # Quality check
                if quality_requirements:
                    min_res = quality_requirements.get("min_resolution", 512)
                    if width >= min_res and height >= min_res:
                        response["quality_check"] = "passed"
                    else:
                        response["quality_check"] = "failed"
                else:
                    response["quality_check"] = "passed"

                return response

            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff

        return {
            "error": str(last_error),
            "type": "ai_image",
            "tool": "dalle",
        }

    async def _call_dalle(
        self,
        prompt: str,
        size: str,
        quality: str,
        style: str,
    ) -> dict[str, Any]:
        """
        Call DALL-E API.

        This is a separate method to allow mocking in tests.
        """
        if not self.openai_api_key:
            raise ValueError("OpenAI API key not configured")

        client = await self._get_http_client()

        response = await client.post(
            "https://api.openai.com/v1/images/generations",
            json={
                "model": "dall-e-3",
                "prompt": prompt,
                "size": size,
                "quality": quality,
                "style": style,
                "n": 1,
            },
            headers={
                "Authorization": f"Bearer {self.openai_api_key}",
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()
        data = response.json()

        image_data = data["data"][0]
        return {
            "image_url": image_data["url"],
            "revised_prompt": image_data.get("revised_prompt", prompt),
            "cost": 0.04 if quality == "standard" else 0.08,
        }

    async def _download_image(self, url: str, output_path: str) -> None:
        """Download image from URL."""
        client = await self._get_http_client()
        response = await client.get(url)
        response.raise_for_status()

        with open(output_path, "wb") as f:
            f.write(response.content)

    async def generate_video(
        self,
        prompt: str,
        duration: int = 5,
        aspect_ratio: str = "9:16",
        max_retries: int = 3,
    ) -> dict[str, Any]:
        """
        Generate video using Runway ML.

        Args:
            prompt: Video generation prompt
            duration: Video duration in seconds (5 or 10)
            aspect_ratio: Aspect ratio (16:9, 9:16)
            max_retries: Maximum retry attempts

        Returns:
            Generated video info
        """
        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                result = await self._call_runway(prompt, duration, aspect_ratio)

                return {
                    "path": result.get("video_path", ""),
                    "type": "ai_video",
                    "tool": "runway",
                    "prompt": prompt,
                    "duration": duration,
                    "cost": 0.25 * duration,  # Approximate
                }

            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)

        return {
            "error": str(last_error),
            "type": "ai_video",
            "tool": "runway",
        }

    async def _call_runway(
        self,
        prompt: str,
        duration: int,
        aspect_ratio: str,
    ) -> dict[str, Any]:
        """
        Call Runway ML API.

        This is a placeholder - actual Runway integration requires their SDK.
        """
        # Runway ML doesn't have a simple REST API
        # This would use their official SDK in production
        raise NotImplementedError("Runway ML integration requires SDK setup")

    async def generate_voiceover(
        self,
        text: str,
        voice_config: dict[str, Any],
        max_retries: int = 3,
    ) -> dict[str, Any]:
        """
        Generate voiceover using TTS.

        Args:
            text: Text to synthesize
            voice_config: Voice configuration (voice_id, style, etc.)
            max_retries: Maximum retry attempts

        Returns:
            Generated audio info
        """
        # Use mock API if provided (for testing)
        if self.tts_api:
            # Extract voice_id and pass remaining config to avoid duplicate kwargs
            voice_id = voice_config.get("voice_id", "")
            extra_config = {k: v for k, v in voice_config.items() if k != "voice_id"}
            result = await self.tts_api.synthesize(
                text,
                voice_id=voice_id,
                **extra_config,
            )
            return {
                "path": result["audio_path"],
                "type": "voiceover",
                "tool": "elevenlabs",
                "duration_seconds": result["duration_seconds"],
                "cost": result.get("cost", 0.01),
                "text": text,
            }

        # Use ElevenLabs if key is configured, otherwise fall back to Edge TTS (free)
        if self.elevenlabs_api_key:
            return await self._generate_elevenlabs_voiceover(text, voice_config, max_retries)
        return await self._generate_edge_tts_voiceover(text, voice_config)

    async def _generate_elevenlabs_voiceover(
        self,
        text: str,
        voice_config: dict[str, Any],
        max_retries: int,
    ) -> dict[str, Any]:
        """Generate voiceover using ElevenLabs API."""
        if not self.elevenlabs_api_key:
            return {"error": "ElevenLabs API key not configured"}

        voice_id = voice_config.get("voice_id", "21m00Tcm4TlvDq8ikWAM")  # Default voice
        model_id = voice_config.get("model_id", "eleven_multilingual_v2")

        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                client = await self._get_http_client()

                response = await client.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                    json={
                        "text": text,
                        "model_id": model_id,
                        "voice_settings": {
                            "stability": voice_config.get("stability", 0.5),
                            "similarity_boost": voice_config.get("similarity_boost", 0.75),
                        },
                    },
                    headers={
                        "xi-api-key": self.elevenlabs_api_key,
                        "Content-Type": "application/json",
                        "Accept": "audio/mpeg",
                    },
                )
                response.raise_for_status()

                # Save audio
                audio_id = str(uuid.uuid4())[:8]
                output_path = self.output_dir / f"vo_{audio_id}.mp3"

                with open(output_path, "wb") as f:
                    f.write(response.content)

                # Estimate duration (rough: ~150 words per minute)
                word_count = len(text.split())
                duration_seconds = (word_count / 150) * 60

                # Cost based on character count
                char_count = len(text)
                cost = (char_count / 1000) * 0.30  # Approximate ElevenLabs pricing

                return {
                    "path": str(output_path),
                    "type": "voiceover",
                    "tool": "elevenlabs",
                    "duration_seconds": duration_seconds,
                    "cost": cost,
                    "text": text,
                    "voice_id": voice_id,
                }

            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)

        return {
            "error": str(last_error),
            "type": "voiceover",
            "tool": "elevenlabs",
        }

    async def _validate_audio_file(self, path: str) -> bool:
        """Validate an audio file using ffprobe.

        Checks that the file is non-empty, ffprobe can read it,
        and the reported duration is > 0.

        Returns True if valid, False otherwise.
        """
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            return False

        try:
            process = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()

            if process.returncode != 0:
                return False

            duration = float(stdout.decode().strip())
            return duration > 0.0
        except Exception:
            return False

    async def _trim_leading_silence(self, path: str) -> bool:
        """Trim leading silence from an audio file using FFmpeg silenceremove.

        Modifies the file in-place (via temp file). Returns True on success.
        """
        tmp_path = path + ".trimmed"
        try:
            process = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y",
                "-i", path,
                "-af", "silenceremove=start_periods=1:start_silence=0.05:start_threshold=-50dB",
                "-c:a", "libmp3lame", "-q:a", "2",
                tmp_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, _ = await process.communicate()

            if process.returncode != 0:
                return False

            # Replace original with trimmed version
            os.replace(tmp_path, path)
            return True
        except Exception:
            return False

    async def _generate_edge_tts_voiceover(
        self,
        text: str,
        voice_config: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate voiceover using Edge TTS (free, no API key)."""
        try:
            import edge_tts
        except ImportError:
            return {"error": "edge-tts not installed. Run: pip install edge-tts"}

        voice = voice_config.get("voice")
        if voice is None:
            # Resolve from catalog if tone is provided
            tone = voice_config.get("tone")
            if tone:
                from .voice_catalog import select_voice

                profile = select_voice(tone)
                voice = profile.edge_tts_name
            else:
                voice = "en-US-ChristopherNeural"
        max_retries = 5
        last_error: str | None = None

        for attempt in range(max_retries):
            audio_id = str(uuid.uuid4())[:8]
            output_path = self.output_dir / f"vo_{audio_id}.mp3"

            try:
                communicate = edge_tts.Communicate(text, voice)
                await communicate.save(str(output_path))

                # Validate with ffprobe: non-zero size, readable, positive duration
                if not await self._validate_audio_file(str(output_path)):
                    last_error = "Edge TTS produced invalid audio file"
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2 ** attempt)
                    continue

                # Trim leading silence (best-effort, don't fail if it doesn't work)
                await self._trim_leading_silence(str(output_path))

                # Estimate duration (~150 words per minute)
                word_count = len(text.split())
                duration_seconds = (word_count / 150) * 60

                return {
                    "path": str(output_path),
                    "type": "voiceover",
                    "tool": "edge_tts",
                    "duration_seconds": duration_seconds,
                    "cost": 0.0,
                    "text": text,
                    "voice": voice,
                }
            except Exception as e:
                last_error = str(e)
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)

        return {
            "error": last_error or "Edge TTS failed after retries",
            "type": "voiceover",
            "tool": "edge_tts",
        }

    async def generate_music(
        self,
        style: str,
        duration: int,
        max_retries: int = 3,
    ) -> dict[str, Any]:
        """
        Generate background music.

        Args:
            style: Music style description
            duration: Duration in seconds
            max_retries: Maximum retry attempts

        Returns:
            Generated music info
        """
        # Placeholder - would use Suno or similar
        return {
            "error": "Music generation not yet implemented",
            "type": "music",
            "style": style,
            "duration": duration,
        }

    async def generate_image_from_image(
        self,
        source_image_path: str,
        motion_prompt: str,
        duration: int = 5,
    ) -> dict[str, Any]:
        """
        Generate video from a source image (image-to-video).

        Args:
            source_image_path: Path to source image
            motion_prompt: Description of desired motion
            duration: Output duration

        Returns:
            Generated video info
        """
        # Placeholder - would use Runway or similar
        return {
            "error": "Image-to-video generation not yet implemented",
            "type": "ai_video",
            "source": source_image_path,
        }

    def get_available_voices(self) -> list[dict[str, Any]]:
        """
        Get list of available TTS voices.

        Returns:
            List of voice configurations
        """
        # Default ElevenLabs voices
        return [
            {"voice_id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel", "style": "conversational"},
            {"voice_id": "AZnzlk1XvdvUeBnXmlld", "name": "Domi", "style": "professional"},
            {"voice_id": "EXAVITQu4vr4xnSDxMaL", "name": "Bella", "style": "soft"},
            {"voice_id": "ErXwobaYiN019PkySvjV", "name": "Antoni", "style": "warm"},
            {"voice_id": "MF3mGyEYCl7XYWbV9V6O", "name": "Elli", "style": "young"},
        ]
