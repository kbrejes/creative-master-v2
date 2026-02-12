"""
Deepgram Aura TTS provider.

Uses the Deepgram Aura API for fast, high-quality text-to-speech.
Cost: ~$0.0135 per 1000 characters.
"""

import uuid
from pathlib import Path

import httpx

from src.providers.base import ProviderCapability, ProviderHealth, ProviderInfo
from src.providers.tts.protocol import TTSRequest, TTSResponse

# Pricing: ~$0.0135 per 1K characters
COST_PER_1K_CHARS = 0.0135

# Available Aura voices
DEEPGRAM_VOICES = {
    # English voices
    "asteria": {"name": "Asteria", "language": "en", "gender": "female", "style": "conversational"},
    "luna": {"name": "Luna", "language": "en", "gender": "female", "style": "soft"},
    "stella": {"name": "Stella", "language": "en", "gender": "female", "style": "professional"},
    "athena": {"name": "Athena", "language": "en", "gender": "female", "style": "authoritative"},
    "hera": {"name": "Hera", "language": "en", "gender": "female", "style": "warm"},
    "orion": {"name": "Orion", "language": "en", "gender": "male", "style": "conversational"},
    "arcas": {"name": "Arcas", "language": "en", "gender": "male", "style": "professional"},
    "perseus": {"name": "Perseus", "language": "en", "gender": "male", "style": "energetic"},
    "angus": {"name": "Angus", "language": "en", "gender": "male", "style": "warm"},
    "orpheus": {"name": "Orpheus", "language": "en", "gender": "male", "style": "authoritative"},
    "helios": {"name": "Helios", "language": "en", "gender": "male", "style": "young"},
    "zeus": {"name": "Zeus", "language": "en", "gender": "male", "style": "deep"},
}

# Default voices by language
DEFAULT_VOICES = {
    "en": "orion",
    "ru": "orion",  # Deepgram uses same voices, handles language automatically
}


class DeepgramTTSProvider:
    """TTS provider using Deepgram Aura API."""

    def __init__(
        self,
        api_key: str,
        output_dir: str = "/tmp/creative_master/tts",
        default_voice: str = "orion",
    ):
        """Initialize the Deepgram TTS provider.

        Args:
            api_key: Deepgram API key
            output_dir: Directory for generated audio files
            default_voice: Default voice model to use

        Raises:
            ValueError: If API key is empty
        """
        if not api_key or not api_key.strip():
            raise ValueError("Deepgram API key is required")

        self._api_key = api_key
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._default_voice = default_voice
        self._http_client: httpx.AsyncClient | None = None
        self._info = ProviderInfo(
            name="deepgram",
            capability=ProviderCapability.TTS,
            health=ProviderHealth.UNKNOWN,
            cost_per_unit=COST_PER_1K_CHARS,
            priority=80,  # High priority - cheap and fast
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
                base_url="https://api.deepgram.com/v1",
                headers={
                    "Authorization": f"Token {self._api_key}",
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
        """Check if the Deepgram API is healthy.

        Returns:
            Provider health status
        """
        try:
            client = await self._get_client()
            # Simple API check - get projects list
            response = await client.get("/projects")

            if response.status_code == 200:
                self._info.health = ProviderHealth.HEALTHY
                return ProviderHealth.HEALTHY
            elif response.status_code == 429:
                self._info.health = ProviderHealth.DEGRADED
                return ProviderHealth.DEGRADED
            else:
                self._info.health = ProviderHealth.UNHEALTHY
                return ProviderHealth.UNHEALTHY

        except Exception:
            self._info.health = ProviderHealth.UNHEALTHY
            return ProviderHealth.UNHEALTHY

    async def synthesize(
        self,
        request: TTSRequest,
        language: str = "en",
    ) -> TTSResponse:
        """Synthesize speech from text.

        Args:
            request: TTS synthesis request
            language: Language code (en, ru, etc.)

        Returns:
            Generated audio response
        """
        voice = request.voice_id or self._default_voice

        # Ensure voice is valid
        if voice not in DEEPGRAM_VOICES:
            voice = self._default_voice

        client = await self._get_client()

        # Deepgram Aura endpoint
        # Model format: aura-{voice}-en
        model = f"aura-{voice}-en"

        response = await client.post(
            "/speak",
            params={"model": model},
            json={"text": request.text},
            headers={"Accept": "audio/mp3"},
        )
        response.raise_for_status()

        # Save audio to file
        audio_id = str(uuid.uuid4())[:8]
        output_path = self._output_dir / f"vo_deepgram_{audio_id}.mp3"

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
            voice_id=voice,
        )

    def get_available_voices(self, language: str = "en") -> list[dict]:
        """Get list of available voices.

        Args:
            language: Language filter (currently all voices support all languages)

        Returns:
            List of voice configurations
        """
        return [
            {"voice_id": vid, **vinfo}
            for vid, vinfo in DEEPGRAM_VOICES.items()
        ]

    def get_default_voice(self, language: str = "en") -> str:
        """Get default voice for a language.

        Args:
            language: Language code

        Returns:
            Voice ID
        """
        return DEFAULT_VOICES.get(language, "orion")
