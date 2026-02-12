"""Music library — royalty-free background music tracks by mood."""

import random
from enum import StrEnum
from pathlib import Path

import httpx
from pydantic import BaseModel


class MusicMood(StrEnum):
    """Music mood categories."""

    UPBEAT = "upbeat"
    CHILL = "chill"
    DRAMATIC = "dramatic"
    CORPORATE = "corporate"
    INSPIRATIONAL = "inspirational"


class MusicTrack(BaseModel):
    """A royalty-free music track."""

    name: str
    url: str
    mood: MusicMood
    duration_seconds: int
    source: str


class MusicLibrary:
    """Catalog of royalty-free background music tracks."""

    def __init__(self) -> None:
        self.tracks: list[MusicTrack] = _DEFAULT_TRACKS.copy()

    async def download_track(
        self,
        track: MusicTrack,
        output_dir: str,
    ) -> str | None:
        """Download a music track to a local directory.

        Returns path to downloaded file, or None on failure.
        """
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_name = track.name.replace(" ", "_").lower()
        output_path = out_dir / f"{safe_name}.mp3"

        try:
            async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
                response = await client.get(track.url)
                response.raise_for_status()
                output_path.write_bytes(response.content)
            return str(output_path)
        except Exception:
            return None


_DEFAULT_TRACKS: list[MusicTrack] = [
    # --- Upbeat ---
    MusicTrack(
        name="Feeling Happy",
        url="https://assets.mixkit.co/music/5/5.mp3",
        mood=MusicMood.UPBEAT,
        duration_seconds=148,
        source="mixkit",
    ),
    MusicTrack(
        name="Fun Times",
        url="https://assets.mixkit.co/music/146/146.mp3",
        mood=MusicMood.UPBEAT,
        duration_seconds=132,
        source="mixkit",
    ),
    # --- Chill ---
    MusicTrack(
        name="Valley Sunset",
        url="https://assets.mixkit.co/music/127/127.mp3",
        mood=MusicMood.CHILL,
        duration_seconds=150,
        source="mixkit",
    ),
    MusicTrack(
        name="Serene View",
        url="https://assets.mixkit.co/music/128/128.mp3",
        mood=MusicMood.CHILL,
        duration_seconds=146,
        source="mixkit",
    ),
    # --- Dramatic ---
    MusicTrack(
        name="Epical Drums",
        url="https://assets.mixkit.co/music/676/676.mp3",
        mood=MusicMood.DRAMATIC,
        duration_seconds=106,
        source="mixkit",
    ),
    MusicTrack(
        name="Dark Cinematic",
        url="https://assets.mixkit.co/music/661/661.mp3",
        mood=MusicMood.DRAMATIC,
        duration_seconds=120,
        source="mixkit",
    ),
    # --- Corporate ---
    MusicTrack(
        name="Deep Urban",
        url="https://assets.mixkit.co/music/623/623.mp3",
        mood=MusicMood.CORPORATE,
        duration_seconds=231,
        source="mixkit",
    ),
    MusicTrack(
        name="Tech Corporate",
        url="https://assets.mixkit.co/music/625/625.mp3",
        mood=MusicMood.CORPORATE,
        duration_seconds=178,
        source="mixkit",
    ),
    # --- Inspirational ---
    MusicTrack(
        name="Tears of Joy",
        url="https://assets.mixkit.co/music/839/839.mp3",
        mood=MusicMood.INSPIRATIONAL,
        duration_seconds=140,
        source="mixkit",
    ),
    MusicTrack(
        name="Beautiful Dream",
        url="https://assets.mixkit.co/music/837/837.mp3",
        mood=MusicMood.INSPIRATIONAL,
        duration_seconds=155,
        source="mixkit",
    ),
]

_LIBRARY = MusicLibrary()


def select_track(
    mood: str,
    min_duration: int = 0,
) -> MusicTrack | None:
    """Select a music track matching mood and minimum duration.

    Falls back to chill mood if requested mood is unknown.
    """
    candidates = [t for t in _LIBRARY.tracks if t.mood == mood]
    if not candidates:
        candidates = [t for t in _LIBRARY.tracks if t.mood == MusicMood.CHILL]

    if min_duration > 0:
        candidates = [t for t in candidates if t.duration_seconds >= min_duration]

    return random.choice(candidates) if candidates else None
