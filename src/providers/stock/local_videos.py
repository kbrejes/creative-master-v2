"""
Local video library provider.

Serves videos from a local directory instead of external APIs like Pexels.
Instant loading, no API costs, trailer-quality drone/nature footage.
"""

import random
from pathlib import Path

from pydantic import BaseModel


class LocalVideo(BaseModel):
    """A local video file."""

    id: str
    filename: str
    path: str
    url: str  # Relative URL for serving
    duration: float | None = None
    width: int = 1080
    height: int = 1920


class LocalVideoLibrary:
    """Library of local video files for instant serving."""

    SUPPORTED_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v"}

    def __init__(self, video_dir: str | Path, serve_prefix: str = "/local-videos"):
        """Initialize the local video library.

        Args:
            video_dir: Directory containing video files
            serve_prefix: URL prefix for serving videos
        """
        self._video_dir = Path(video_dir)
        self._serve_prefix = serve_prefix
        self._videos: list[LocalVideo] = []
        self._loaded = False

    def load(self) -> int:
        """Scan directory and load video metadata.

        Returns:
            Number of videos loaded
        """
        if not self._video_dir.exists():
            raise ValueError(f"Video directory not found: {self._video_dir}")

        self._videos = []
        for file_path in sorted(self._video_dir.iterdir()):
            if file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                video = LocalVideo(
                    id=file_path.stem,
                    filename=file_path.name,
                    path=str(file_path),
                    url=f"{self._serve_prefix}/{file_path.name}",
                )
                self._videos.append(video)

        self._loaded = True
        return len(self._videos)

    @property
    def videos(self) -> list[LocalVideo]:
        """Get all videos."""
        if not self._loaded:
            self.load()
        return self._videos

    @property
    def count(self) -> int:
        """Get number of videos."""
        return len(self.videos)

    def get_random(self, count: int = 1) -> list[LocalVideo]:
        """Get random videos.

        Args:
            count: Number of videos to return

        Returns:
            List of random videos
        """
        videos = self.videos
        if not videos:
            return []
        count = min(count, len(videos))
        return random.sample(videos, count)

    def get_by_id(self, video_id: str) -> LocalVideo | None:
        """Get a video by ID.

        Args:
            video_id: Video ID (filename without extension)

        Returns:
            Video or None if not found
        """
        for video in self.videos:
            if video.id == video_id:
                return video
        return None

    def get_for_shot(self, shot_index: int, total_shots: int) -> LocalVideo:
        """Get a video for a specific shot, ensuring variety.

        Distributes videos across shots to avoid repetition.

        Args:
            shot_index: Index of the shot (0-based)
            total_shots: Total number of shots

        Returns:
            Video for this shot
        """
        videos = self.videos
        if not videos:
            raise ValueError("No videos loaded")

        # Use modulo to cycle through videos, with offset for variety
        idx = (shot_index * 7) % len(videos)  # 7 is a prime for better distribution
        return videos[idx]

    def get_options_for_shot(self, shot_index: int, count: int = 5) -> list[LocalVideo]:
        """Get multiple video options for a shot (for user selection).

        Uses random sampling to avoid repetitive video selection across generations.

        Args:
            shot_index: Index of the shot (unused, kept for API compatibility)
            count: Number of options to return

        Returns:
            List of random video options
        """
        videos = self.videos
        if not videos:
            return []

        # Random sample for variety - each generation gets different videos
        count = min(count, len(videos))
        return random.sample(videos, count)


# Default library instance (lazy loaded)
_default_library: LocalVideoLibrary | None = None


def get_default_library(video_dir: str | Path | None = None) -> LocalVideoLibrary:
    """Get or create the default video library.

    Args:
        video_dir: Video directory (required on first call)

    Returns:
        LocalVideoLibrary instance
    """
    global _default_library
    if _default_library is None:
        if video_dir is None:
            raise ValueError("video_dir required on first call")
        _default_library = LocalVideoLibrary(video_dir)
    return _default_library
