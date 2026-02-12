"""
Edge TTS provider - free Microsoft text-to-speech.

Uses the edge-tts library for high-quality, free TTS.
Cost: FREE (no API key required).
"""

import uuid
from pathlib import Path

import edge_tts

from src.providers.base import ProviderCapability, ProviderHealth, ProviderInfo
from src.providers.tts.protocol import TTSRequest, TTSResponse


class EdgeTTSProvider:
    """TTS provider using Microsoft Edge's free TTS service."""

    # Default voice (high quality, natural)
    DEFAULT_VOICE = "en-US-JennyNeural"

    def __init__(
        self,
        output_dir: str = "/tmp/creative_master/tts",
        default_voice: str = DEFAULT_VOICE,
    ):
        """Initialize the Edge TTS provider.

        Args:
            output_dir: Directory for generated audio files
            default_voice: Default voice to use (e.g., "en-US-JennyNeural")
        """
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._default_voice = default_voice
        self._info = ProviderInfo(
            name="edge_tts",
            capability=ProviderCapability.TTS,
            health=ProviderHealth.UNKNOWN,
            cost_per_unit=0.0,  # FREE
            priority=10,  # High priority (prefer free)
            is_local=False,
        )

    @property
    def info(self) -> ProviderInfo:
        """Get provider information."""
        return self._info

    async def health_check(self) -> ProviderHealth:
        """Check if Edge TTS is available.

        Returns:
            Provider health status
        """
        try:
            # Try to list voices - if this works, service is available
            voices = await edge_tts.list_voices()
            if voices:
                self._info.health = ProviderHealth.HEALTHY
                return ProviderHealth.HEALTHY
            else:
                self._info.health = ProviderHealth.DEGRADED
                return ProviderHealth.DEGRADED
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
        # Use voice_id as the Edge TTS voice name
        voice = request.voice_id or self._default_voice

        # Generate unique filename
        audio_id = str(uuid.uuid4())[:8]
        output_path = self._output_dir / f"vo_{audio_id}.mp3"

        # Synthesize
        communicate = edge_tts.Communicate(request.text, voice)
        await communicate.save(str(output_path))

        # Estimate duration (~150 words per minute)
        word_count = len(request.text.split())
        duration_seconds = (word_count / 150) * 60

        return TTSResponse(
            audio_path=str(output_path),
            duration_seconds=duration_seconds,
            cost=0.0,  # Free!
            provider=self._info.name,
            character_count=len(request.text),
            voice_id=voice,
        )

    @staticmethod
    async def list_voices(locale: str | None = None) -> list[dict]:
        """Get list of available voices.

        Args:
            locale: Optional locale filter (e.g., "en-US", "ru-RU")

        Returns:
            List of voice configurations
        """
        voices = await edge_tts.list_voices()

        if locale:
            voices = [v for v in voices if v.get("Locale", "").startswith(locale)]

        return [
            {
                "voice_id": v["ShortName"],
                "name": v["FriendlyName"],
                "locale": v["Locale"],
                "gender": v["Gender"],
            }
            for v in voices
        ]
