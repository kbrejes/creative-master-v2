"""
ElevenLabs TTS provider.

Uses the ElevenLabs API for high-quality text-to-speech.
Cost: ~$0.30 per 1000 characters.
"""

import uuid
from pathlib import Path

import httpx

from src.providers.base import ProviderCapability, ProviderHealth, ProviderInfo
from src.providers.tts.protocol import TTSRequest, TTSResponse

# Pricing: ~$0.30 per 1K characters
COST_PER_1K_CHARS = 0.30


class ElevenLabsProvider:
    """TTS provider using ElevenLabs API."""

    # Default voices
    DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # Rachel

    def __init__(
        self,
        api_key: str,
        output_dir: str = "/tmp/creative_master/tts",
        default_voice_id: str = DEFAULT_VOICE_ID,
    ):
        """Initialize the ElevenLabs provider.

        Args:
            api_key: ElevenLabs API key
            output_dir: Directory for generated audio files
            default_voice_id: Default voice to use

        Raises:
            ValueError: If API key is empty
        """
        if not api_key or not api_key.strip():
            raise ValueError("ElevenLabs API key is required")

        self._api_key = api_key
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._default_voice_id = default_voice_id
        self._http_client: httpx.AsyncClient | None = None
        self._info = ProviderInfo(
            name="elevenlabs",
            capability=ProviderCapability.TTS,
            health=ProviderHealth.UNKNOWN,
            cost_per_unit=COST_PER_1K_CHARS,
            priority=50,  # Mid-tier priority
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
                base_url="https://api.elevenlabs.io/v1",
                headers={
                    "xi-api-key": self._api_key,
                    "Content-Type": "application/json",
                },
                timeout=60.0,
            )
        return self._http_client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    async def health_check(self) -> ProviderHealth:
        """Check if the ElevenLabs API is healthy.

        Returns:
            Provider health status
        """
        try:
            client = await self._get_client()
            response = await client.get("/user")

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

    async def synthesize(self, request: TTSRequest) -> TTSResponse:
        """Synthesize speech from text.

        Args:
            request: TTS synthesis request

        Returns:
            Generated audio response
        """
        voice_id = request.voice_id or self._default_voice_id
        model_id = request.model_id or "eleven_multilingual_v2"

        client = await self._get_client()

        response = await client.post(
            f"/text-to-speech/{voice_id}",
            json={
                "text": request.text,
                "model_id": model_id,
                "voice_settings": {
                    "stability": request.stability,
                    "similarity_boost": request.similarity_boost,
                },
            },
            headers={"Accept": "audio/mpeg"},
        )
        response.raise_for_status()

        # Save audio to file
        audio_id = str(uuid.uuid4())[:8]
        output_path = self._output_dir / f"vo_{audio_id}.mp3"

        with open(output_path, "wb") as f:
            f.write(response.content)

        # Calculate cost and duration
        char_count = len(request.text)
        cost = (char_count / 1000) * COST_PER_1K_CHARS

        # Estimate duration (~150 words per minute)
        word_count = len(request.text.split())
        duration_seconds = (word_count / 150) * 60

        return TTSResponse(
            audio_path=str(output_path),
            duration_seconds=duration_seconds,
            cost=cost,
            provider=self._info.name,
            character_count=char_count,
            voice_id=voice_id,
        )

    def get_available_voices(self) -> list[dict]:
        """Get list of available voices.

        Returns:
            List of voice configurations
        """
        return [
            {"voice_id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel", "style": "conversational"},
            {"voice_id": "AZnzlk1XvdvUeBnXmlld", "name": "Domi", "style": "professional"},
            {"voice_id": "EXAVITQu4vr4xnSDxMaL", "name": "Bella", "style": "soft"},
            {"voice_id": "ErXwobaYiN019PkySvjV", "name": "Antoni", "style": "warm"},
            {"voice_id": "MF3mGyEYCl7XYWbV9V6O", "name": "Elli", "style": "young"},
        ]
