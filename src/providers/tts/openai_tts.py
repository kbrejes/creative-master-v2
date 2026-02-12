"""
OpenAI TTS provider.

Uses the OpenAI TTS API for high-quality text-to-speech.
Cost: $0.015 per 1000 characters (tts-1) or $0.030 (tts-1-hd).
"""

import uuid
from pathlib import Path

import httpx

from src.providers.base import ProviderCapability, ProviderHealth, ProviderInfo
from src.providers.tts.protocol import TTSRequest, TTSResponse

# Pricing per 1K characters
COST_PER_1K_CHARS = {
    "tts-1": 0.015,
    "tts-1-hd": 0.030,
}

# Available OpenAI voices
OPENAI_VOICES = {
    "alloy": {"name": "Alloy", "gender": "neutral", "style": "balanced"},
    "echo": {"name": "Echo", "gender": "male", "style": "warm"},
    "fable": {"name": "Fable", "gender": "neutral", "style": "expressive"},
    "onyx": {"name": "Onyx", "gender": "male", "style": "deep"},
    "nova": {"name": "Nova", "gender": "female", "style": "warm"},
    "shimmer": {"name": "Shimmer", "gender": "female", "style": "clear"},
}

# Recommended voices by use case
VOICE_RECOMMENDATIONS = {
    "conversational": "nova",
    "professional": "onyx",
    "energetic": "alloy",
    "warm": "echo",
    "authoritative": "onyx",
    "young": "shimmer",
    "default": "nova",
}


class OpenAITTSProvider:
    """TTS provider using OpenAI TTS API."""

    def __init__(
        self,
        api_key: str,
        output_dir: str = "/tmp/creative_master/tts",
        default_voice: str = "nova",
        model: str = "tts-1",
    ):
        """Initialize the OpenAI TTS provider.

        Args:
            api_key: OpenAI API key
            output_dir: Directory for generated audio files
            default_voice: Default voice to use (alloy, echo, fable, onyx, nova, shimmer)
            model: TTS model to use (tts-1 or tts-1-hd)

        Raises:
            ValueError: If API key is empty or invalid model
        """
        if not api_key or not api_key.strip():
            raise ValueError("OpenAI API key is required")

        if model not in COST_PER_1K_CHARS:
            raise ValueError(f"Invalid model: {model}. Use 'tts-1' or 'tts-1-hd'")

        self._api_key = api_key
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._default_voice = default_voice
        self._model = model
        self._http_client: httpx.AsyncClient | None = None
        self._info = ProviderInfo(
            name="openai-tts",
            capability=ProviderCapability.TTS,
            health=ProviderHealth.UNKNOWN,
            cost_per_unit=COST_PER_1K_CHARS[model],
            priority=70,  # High priority - good quality, reasonable cost
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
                base_url="https://api.openai.com/v1",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
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
        """Check if the OpenAI API is healthy.

        Returns:
            Provider health status
        """
        try:
            client = await self._get_client()
            response = await client.get("/models")

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

        OpenAI TTS automatically detects language from input text,
        so no explicit language parameter is needed in the API call.

        Args:
            request: TTS synthesis request
            language: Language code (for logging/tracking, auto-detected by API)

        Returns:
            Generated audio response
        """
        voice = request.voice_id or self._default_voice
        model = request.model_id or self._model

        # Ensure voice is valid
        if voice not in OPENAI_VOICES:
            voice = self._default_voice

        # Ensure model is valid
        if model not in COST_PER_1K_CHARS:
            model = self._model

        client = await self._get_client()

        response = await client.post(
            "/audio/speech",
            json={
                "model": model,
                "input": request.text,
                "voice": voice,
                "response_format": "mp3",
                "speed": 1.0,
            },
        )
        response.raise_for_status()

        # Save audio to file
        audio_id = str(uuid.uuid4())[:8]
        output_path = self._output_dir / f"vo_openai_{audio_id}.mp3"

        with open(output_path, "wb") as f:
            f.write(response.content)

        # Calculate cost and duration
        char_count = len(request.text)
        cost = (char_count / 1000) * COST_PER_1K_CHARS[model]

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

    def get_available_voices(self) -> list[dict]:
        """Get list of available voices.

        Returns:
            List of voice configurations
        """
        return [
            {"voice_id": vid, **vinfo}
            for vid, vinfo in OPENAI_VOICES.items()
        ]

    def get_voice_for_tone(self, tone: str) -> str:
        """Get recommended voice for a tone.

        Args:
            tone: Desired tone (conversational, professional, etc.)

        Returns:
            Voice ID
        """
        return VOICE_RECOMMENDATIONS.get(tone, VOICE_RECOMMENDATIONS["default"])

    def set_model(self, model: str) -> None:
        """Switch between tts-1 and tts-1-hd models.

        Args:
            model: Model ID (tts-1 or tts-1-hd)
        """
        if model in COST_PER_1K_CHARS:
            self._model = model
            self._info.cost_per_unit = COST_PER_1K_CHARS[model]
