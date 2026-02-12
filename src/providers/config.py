"""
Provider configuration management.

Loads configuration from environment variables and YAML files.
"""

import os
from pathlib import Path

from pydantic import BaseModel, Field

from src.providers.providers.base import ProviderCapability


class CapabilityConfig(BaseModel):
    """Configuration for a single capability (e.g., LLM, image generation)."""

    default_provider: str = Field(..., description="Default provider for this capability")
    fallback_chain: list[str] = Field(
        default_factory=list,
        description="Providers to try if default fails",
    )


class ProviderConfig(BaseModel):
    """Configuration for all providers."""

    capabilities: dict[ProviderCapability, CapabilityConfig] = Field(
        default_factory=dict,
        description="Configuration per capability",
    )
    api_keys: dict[str, str] = Field(
        default_factory=dict,
        description="API keys by provider name",
    )

    def get_default_provider(self, capability: ProviderCapability) -> str | None:
        """Get the default provider for a capability."""
        cap_config = self.capabilities.get(capability)
        return cap_config.default_provider if cap_config else None

    def get_fallback_chain(self, capability: ProviderCapability) -> list[str]:
        """Get the fallback chain for a capability."""
        cap_config = self.capabilities.get(capability)
        return cap_config.fallback_chain if cap_config else []

    def has_api_key(self, provider: str) -> bool:
        """Check if an API key is available for a provider."""
        return provider in self.api_keys

    @classmethod
    def from_env(cls) -> "ProviderConfig":
        """Load configuration from environment variables."""
        api_keys: dict[str, str] = {}

        # Map of provider name to environment variable
        key_mappings = {
            "replicate": "REPLICATE_API_TOKEN",
            "anthropic": "ANTHROPIC_API_KEY",
            "elevenlabs": "ELEVENLABS_API_KEY",
            "pexels": "PEXELS_API_KEY",
            "openai": "OPENAI_API_KEY",
        }

        for provider, env_var in key_mappings.items():
            value = os.environ.get(env_var)
            if value:
                api_keys[provider] = value

        return cls(api_keys=api_keys)

    @classmethod
    def from_yaml(
        cls,
        path: Path,
        load_env_keys: bool = False,
    ) -> "ProviderConfig":
        """Load configuration from a YAML file.

        Args:
            path: Path to the YAML configuration file
            load_env_keys: If True, also load API keys from environment

        Returns:
            ProviderConfig loaded from file (or empty if file doesn't exist)
        """
        if not path.exists():
            return cls()

        try:
            import yaml

            with open(path) as f:
                data = yaml.safe_load(f)
        except Exception:
            return cls()

        if not data:
            return cls()

        # Parse capabilities
        capabilities: dict[ProviderCapability, CapabilityConfig] = {}
        raw_capabilities = data.get("capabilities", {})

        for cap_name, cap_config in raw_capabilities.items():
            try:
                capability = ProviderCapability(cap_name)
                capabilities[capability] = CapabilityConfig(
                    default_provider=cap_config.get("default_provider", ""),
                    fallback_chain=cap_config.get("fallback_chain", []),
                )
            except ValueError:
                continue

        # Load API keys
        api_keys: dict[str, str] = {}
        if load_env_keys:
            env_config = cls.from_env()
            api_keys = env_config.api_keys

        return cls(capabilities=capabilities, api_keys=api_keys)
