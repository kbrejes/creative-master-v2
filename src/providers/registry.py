"""
Provider registry - the router that selects providers.

Manages provider registration, health checking, and selection based on
configuration, health, cost, and preferences.
"""

from typing import Protocol, runtime_checkable

from src.providers.base import (
    ProviderCapability,
    ProviderHealth,
    ProviderInfo,
)
from src.providers.config import ProviderConfig


class NoProviderAvailableError(Exception):
    """Raised when no suitable provider is available."""

    def __init__(self, capability: ProviderCapability, reason: str = ""):
        self.capability = capability
        message = f"No provider available for {capability.value}"
        if reason:
            message = f"{message}: {reason}"
        super().__init__(message)


@runtime_checkable
class ProviderProtocol(Protocol):
    """Protocol for providers that can be registered."""

    @property
    def info(self) -> ProviderInfo:
        """Get provider information."""
        ...

    async def health_check(self) -> ProviderHealth:
        """Check provider health."""
        ...


class ProviderRegistry:
    """Registry that manages and selects providers."""

    def __init__(self, config: ProviderConfig | None = None):
        """Initialize registry.

        Args:
            config: Optional configuration for provider selection preferences
        """
        self._providers: dict[str, ProviderProtocol] = {}
        self._config = config or ProviderConfig()

    def register(self, provider: ProviderProtocol) -> None:
        """Register a provider.

        Args:
            provider: Provider to register
        """
        self._providers[provider.info.name] = provider

    def get_provider(self, name: str) -> ProviderProtocol | None:
        """Get a provider by name.

        Args:
            name: Provider name

        Returns:
            Provider if found, None otherwise
        """
        return self._providers.get(name)

    def list_providers(
        self,
        capability: ProviderCapability | None = None,
    ) -> list[ProviderInfo]:
        """List registered providers.

        Args:
            capability: Optional capability filter

        Returns:
            List of provider info for matching providers
        """
        infos = [p.info for p in self._providers.values()]

        if capability is not None:
            infos = [i for i in infos if i.capability == capability]

        return infos

    def select(
        self,
        capability: ProviderCapability,
        prefer_local: bool = False,
        prefer_cheap: bool = False,
    ) -> ProviderProtocol:
        """Select the best provider for a capability.

        Selection order:
        1. Config default provider (if healthy)
        2. Config fallback chain (first healthy)
        3. Preference sorting (local, cheap, priority)
        4. Any healthy/degraded provider

        Args:
            capability: Required capability
            prefer_local: Prefer local providers
            prefer_cheap: Prefer cheaper providers

        Returns:
            Selected provider

        Raises:
            NoProviderAvailableError: If no suitable provider found
        """
        # Get all providers with this capability
        candidates = [
            p for p in self._providers.values() if p.info.capability == capability
        ]

        if not candidates:
            raise NoProviderAvailableError(capability, "no providers registered")

        # Filter to usable (healthy, degraded, or unknown - exclude only unhealthy)
        usable = [
            p
            for p in candidates
            if p.info.health != ProviderHealth.UNHEALTHY
        ]

        if not usable:
            raise NoProviderAvailableError(capability, "all providers unhealthy")

        # Check config for default provider
        default_name = self._config.get_default_provider(capability)
        if default_name:
            for p in usable:
                if p.info.name == default_name:
                    return p

            # Check fallback chain
            for fallback_name in self._config.get_fallback_chain(capability):
                for p in usable:
                    if p.info.name == fallback_name:
                        return p

        # Sort by preferences
        def sort_key(p: ProviderProtocol) -> tuple:
            info = p.info
            # Lower is better for all keys
            local_score = 0 if (prefer_local and info.is_local) else 1
            cost_score = info.cost_per_unit if prefer_cheap else 0
            # Health: HEALTHY=0, UNKNOWN=1, DEGRADED=2
            health_scores = {
                ProviderHealth.HEALTHY: 0,
                ProviderHealth.UNKNOWN: 1,
                ProviderHealth.DEGRADED: 2,
            }
            health_score = health_scores.get(info.health, 3)
            return (health_score, local_score, cost_score, info.priority)

        usable.sort(key=sort_key)
        return usable[0]

    async def check_health(self, name: str) -> ProviderHealth:
        """Check health of a specific provider.

        Args:
            name: Provider name

        Returns:
            Updated health status
        """
        provider = self._providers.get(name)
        if not provider:
            return ProviderHealth.UNKNOWN

        health = await provider.health_check()
        # Update the provider's info with new health status
        provider.info.health = health
        return health

    async def check_all_health(self) -> dict[str, ProviderHealth]:
        """Check health of all registered providers.

        Returns:
            Dict mapping provider name to health status
        """
        results = {}
        for name in self._providers:
            results[name] = await self.check_health(name)
        return results
