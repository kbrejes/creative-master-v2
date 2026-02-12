"""
Provider abstraction layer for AI services.

This module provides an OpenRouter-style abstraction for easily swapping between
expensive (OpenAI, DALL-E) and cheap/free (Replicate, Ollama, Coqui) providers.
"""

from src.providers.providers.base import (
    ProviderCapability,
    ProviderHealth,
    ProviderInfo,
    ProviderProtocol,
)

__all__ = [
    "ProviderCapability",
    "ProviderHealth",
    "ProviderInfo",
    "ProviderProtocol",
]
