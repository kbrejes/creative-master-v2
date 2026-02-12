"""Character library — select characters for UGC talking head generation."""

from __future__ import annotations

from pathlib import Path

from .talking_head import CharacterProfile

_CACHE_DIR = Path.home() / ".cache" / "creative_master" / "characters"


async def ensure_character_image(character: CharacterProfile) -> str:
    """Download and cache a character image if needed.

    If image_path is a URL, downloads it and returns the local cache path.
    If already a local path, returns it as-is.

    Args:
        character: The character whose image to ensure.

    Returns:
        Local file path to the character image.
    """
    if not character.image_path.startswith("http"):
        return character.image_path

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _CACHE_DIR / f"{character.character_id}.png"
    if cache_path.exists():
        return str(cache_path)

    import httpx

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        resp = await client.get(character.image_path)
        resp.raise_for_status()
        cache_path.write_bytes(resp.content)

    return str(cache_path)

# Default character profiles — image URLs point to royalty-free stock headshots.
DEFAULT_CHARACTERS: list[CharacterProfile] = [
    CharacterProfile(
        character_id="ch-default-m1",
        name="Alex",
        image_path="https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=512",
        gender="male",
        age_range="25-35",
        style="casual",
        tags=["tech", "startup"],
    ),
    CharacterProfile(
        character_id="ch-default-m2",
        name="James",
        image_path="https://images.unsplash.com/photo-1472099645785-5658abf4ff4e?w=512",
        gender="male",
        age_range="30-40",
        style="professional",
        tags=["corporate", "finance"],
    ),
    CharacterProfile(
        character_id="ch-default-f1",
        name="Maya",
        image_path="https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=512",
        gender="female",
        age_range="25-35",
        style="casual",
        tags=["lifestyle", "health"],
    ),
    CharacterProfile(
        character_id="ch-default-f2",
        name="Sarah",
        image_path="https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?w=512",
        gender="female",
        age_range="30-40",
        style="professional",
        tags=["corporate", "education"],
    ),
]


class CharacterLibrary:
    """Library of available characters for talking head generation."""

    def __init__(
        self,
        characters: list[CharacterProfile] | None = None,
    ) -> None:
        self._characters: list[CharacterProfile] = characters or []

    @classmethod
    def load_defaults(cls) -> CharacterLibrary:
        """Create a library pre-loaded with default characters."""
        return cls(characters=list(DEFAULT_CHARACTERS))

    def select_character(
        self,
        gender: str | None = None,
        age_range: str | None = None,
        style: str | None = None,
    ) -> CharacterProfile | None:
        """Select a character matching the given filters.

        Returns the first match, or None if no characters match.
        """
        candidates = self._characters
        if gender is not None:
            candidates = [c for c in candidates if c.gender == gender]
        if age_range is not None:
            candidates = [c for c in candidates if c.age_range == age_range]
        if style is not None:
            candidates = [c for c in candidates if c.style == style]
        return candidates[0] if candidates else None

    def list_characters(self) -> list[CharacterProfile]:
        """List all characters in the library."""
        return list(self._characters)
