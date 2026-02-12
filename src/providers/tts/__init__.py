"""TTS (Text-to-Speech) providers."""

from src.providers.providers.tts.protocol import (
    TTSProviderProtocol,
    TTSRequest,
    TTSResponse,
)
from src.providers.providers.tts.deepgram import DeepgramTTSProvider
from src.providers.providers.tts.openai_tts import OpenAITTSProvider
from src.providers.providers.tts.elevenlabs import ElevenLabsProvider

__all__ = [
    "TTSProviderProtocol",
    "TTSRequest",
    "TTSResponse",
    "DeepgramTTSProvider",
    "OpenAITTSProvider",
    "ElevenLabsProvider",
]
