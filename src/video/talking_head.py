"""UGC talking head — protocol, models, and tier definitions."""

from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class TalkingHeadTier(StrEnum):
    """Provider cost tiers for talking head generation."""

    FREE = "free"
    CHEAP = "cheap"
    MEDIUM = "medium"
    PREMIUM = "premium"


class CharacterProfile(BaseModel):
    """A character available for talking head generation."""

    character_id: str
    name: str
    image_path: str
    gender: str
    age_range: str
    style: str
    tags: list[str] = Field(default_factory=list)


class TalkingHeadResult(BaseModel):
    """Result of a talking head generation."""

    video_path: str
    duration_seconds: float
    character_id: str
    provider: str
    cost: float = 0.0


@runtime_checkable
class TalkingHeadProvider(Protocol):
    """Protocol for talking head video generation providers."""

    async def generate(
        self,
        character_image_path: str,
        audio_path: str,
        output_path: str,
    ) -> TalkingHeadResult: ...

    async def health_check(self) -> bool: ...
