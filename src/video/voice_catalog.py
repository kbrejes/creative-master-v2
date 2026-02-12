"""Voice catalog — curated Edge TTS voices mapped by tone and gender."""

from enum import StrEnum

from pydantic import BaseModel


class Gender(StrEnum):
    """Voice gender."""

    MALE = "male"
    FEMALE = "female"


class VoiceProfile(BaseModel):
    """A curated Edge TTS voice profile."""

    voice_id: str
    name: str
    gender: Gender
    tone: str
    description: str
    edge_tts_name: str
    locale: str = "en-US"


class VoiceCatalog:
    """Catalog of curated Edge TTS voices."""

    def __init__(self) -> None:
        self.voices: list[VoiceProfile] = _DEFAULT_VOICES.copy()


_DEFAULT_VOICES: list[VoiceProfile] = [
    # conversational
    VoiceProfile(
        voice_id="guy-neural",
        name="Guy",
        gender=Gender.MALE,
        tone="conversational",
        description="Friendly conversational male voice",
        edge_tts_name="en-US-GuyNeural",
    ),
    VoiceProfile(
        voice_id="jenny-neural",
        name="Jenny",
        gender=Gender.FEMALE,
        tone="conversational",
        description="Friendly conversational female voice",
        edge_tts_name="en-US-JennyNeural",
    ),
    # professional
    VoiceProfile(
        voice_id="brian-neural",
        name="Brian",
        gender=Gender.MALE,
        tone="professional",
        description="Polished professional male voice",
        edge_tts_name="en-US-BrianNeural",
    ),
    VoiceProfile(
        voice_id="aria-neural",
        name="Aria",
        gender=Gender.FEMALE,
        tone="professional",
        description="Polished professional female voice",
        edge_tts_name="en-US-AriaNeural",
    ),
    # energetic
    VoiceProfile(
        voice_id="steffan-neural",
        name="Steffan",
        gender=Gender.MALE,
        tone="energetic",
        description="Upbeat energetic male voice",
        edge_tts_name="en-US-SteffanNeural",
    ),
    VoiceProfile(
        voice_id="ava-neural",
        name="Ava",
        gender=Gender.FEMALE,
        tone="energetic",
        description="Upbeat energetic female voice",
        edge_tts_name="en-US-AvaNeural",
    ),
    # warm
    VoiceProfile(
        voice_id="eric-neural",
        name="Eric",
        gender=Gender.MALE,
        tone="warm",
        description="Warm reassuring male voice",
        edge_tts_name="en-US-EricNeural",
    ),
    VoiceProfile(
        voice_id="ana-neural",
        name="Ana",
        gender=Gender.FEMALE,
        tone="warm",
        description="Warm reassuring female voice",
        edge_tts_name="en-US-AnaNeural",
    ),
    # authoritative
    VoiceProfile(
        voice_id="roger-neural",
        name="Roger",
        gender=Gender.MALE,
        tone="authoritative",
        description="Strong authoritative male voice",
        edge_tts_name="en-US-RogerNeural",
    ),
    VoiceProfile(
        voice_id="michelle-neural",
        name="Michelle",
        gender=Gender.FEMALE,
        tone="authoritative",
        description="Strong authoritative female voice",
        edge_tts_name="en-US-MichelleNeural",
    ),
    # young
    VoiceProfile(
        voice_id="andrew-neural",
        name="Andrew",
        gender=Gender.MALE,
        tone="young",
        description="Youthful casual male voice",
        edge_tts_name="en-US-AndrewNeural",
    ),
    VoiceProfile(
        voice_id="emma-neural",
        name="Emma",
        gender=Gender.FEMALE,
        tone="young",
        description="Youthful casual female voice",
        edge_tts_name="en-US-EmmaNeural",
    ),
]

_LOCALE_VOICES: list[VoiceProfile] = [
    # Russian (ru-RU)
    VoiceProfile(
        voice_id="dmitry-neural",
        name="Dmitry",
        gender=Gender.MALE,
        tone="conversational",
        description="Conversational Russian male voice",
        edge_tts_name="ru-RU-DmitryNeural",
        locale="ru-RU",
    ),
    VoiceProfile(
        voice_id="svetlana-neural",
        name="Svetlana",
        gender=Gender.FEMALE,
        tone="conversational",
        description="Conversational Russian female voice",
        edge_tts_name="ru-RU-SvetlanaNeural",
        locale="ru-RU",
    ),
    # Spanish (es-ES)
    VoiceProfile(
        voice_id="alvaro-neural",
        name="Alvaro",
        gender=Gender.MALE,
        tone="conversational",
        description="Conversational Spanish male voice",
        edge_tts_name="es-ES-AlvaroNeural",
        locale="es-ES",
    ),
    VoiceProfile(
        voice_id="elvira-neural",
        name="Elvira",
        gender=Gender.FEMALE,
        tone="conversational",
        description="Conversational Spanish female voice",
        edge_tts_name="es-ES-ElviraNeural",
        locale="es-ES",
    ),
    # French (fr-FR)
    VoiceProfile(
        voice_id="henri-neural",
        name="Henri",
        gender=Gender.MALE,
        tone="conversational",
        description="Conversational French male voice",
        edge_tts_name="fr-FR-HenriNeural",
        locale="fr-FR",
    ),
    VoiceProfile(
        voice_id="denise-neural",
        name="Denise",
        gender=Gender.FEMALE,
        tone="conversational",
        description="Conversational French female voice",
        edge_tts_name="fr-FR-DeniseNeural",
        locale="fr-FR",
    ),
    # German (de-DE)
    VoiceProfile(
        voice_id="conrad-neural",
        name="Conrad",
        gender=Gender.MALE,
        tone="conversational",
        description="Conversational German male voice",
        edge_tts_name="de-DE-ConradNeural",
        locale="de-DE",
    ),
    VoiceProfile(
        voice_id="katja-neural",
        name="Katja",
        gender=Gender.FEMALE,
        tone="conversational",
        description="Conversational German female voice",
        edge_tts_name="de-DE-KatjaNeural",
        locale="de-DE",
    ),
    # Portuguese (pt-BR)
    VoiceProfile(
        voice_id="antonio-neural",
        name="Antonio",
        gender=Gender.MALE,
        tone="conversational",
        description="Conversational Brazilian Portuguese male voice",
        edge_tts_name="pt-BR-AntonioNeural",
        locale="pt-BR",
    ),
    VoiceProfile(
        voice_id="francisca-neural",
        name="Francisca",
        gender=Gender.FEMALE,
        tone="conversational",
        description="Conversational Brazilian Portuguese female voice",
        edge_tts_name="pt-BR-FranciscaNeural",
        locale="pt-BR",
    ),
    # Italian (it-IT)
    VoiceProfile(
        voice_id="diego-neural",
        name="Diego",
        gender=Gender.MALE,
        tone="conversational",
        description="Conversational Italian male voice",
        edge_tts_name="it-IT-DiegoNeural",
        locale="it-IT",
    ),
    VoiceProfile(
        voice_id="elsa-neural",
        name="Elsa",
        gender=Gender.FEMALE,
        tone="conversational",
        description="Conversational Italian female voice",
        edge_tts_name="it-IT-ElsaNeural",
        locale="it-IT",
    ),
]

_CATALOG = VoiceCatalog()


def select_voice(
    tone: str,
    gender: Gender | None = None,
    locale: str = "en-US",
) -> VoiceProfile:
    """Pick the best voice for a tone, optionally filtered by gender and locale.

    For non-en-US locales, searches _LOCALE_VOICES first.
    Falls back to en-US conversational if locale/tone is unknown.
    """
    all_voices = _CATALOG.voices + _LOCALE_VOICES

    # Filter by locale
    locale_voices = [v for v in all_voices if v.locale == locale]
    if not locale_voices:
        # Unknown locale — fall back to en-US
        locale_voices = [v for v in all_voices if v.locale == "en-US"]

    # Filter by tone
    candidates = [v for v in locale_voices if v.tone == tone]
    if not candidates:
        candidates = [v for v in locale_voices if v.tone == "conversational"]
    if not candidates:
        candidates = locale_voices

    # Filter by gender
    if gender is not None:
        filtered = [v for v in candidates if v.gender == gender]
        if filtered:
            candidates = filtered

    return candidates[0]


def get_voice_by_name(name: str) -> VoiceProfile | None:
    """Look up a voice by its display name."""
    for voice in _CATALOG.voices:
        if voice.name == name:
            return voice
    return None


def list_voices(
    tone: str | None = None,
    gender: Gender | None = None,
    locale: str | None = None,
) -> list[VoiceProfile]:
    """List voices with optional filters."""
    result = _CATALOG.voices + _LOCALE_VOICES
    if locale is not None:
        result = [v for v in result if v.locale == locale]
    if tone is not None:
        result = [v for v in result if v.tone == tone]
    if gender is not None:
        result = [v for v in result if v.gender == gender]
    return result
