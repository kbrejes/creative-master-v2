"""UGC talking head provider factory."""

from ..talking_head import TalkingHeadProvider
from .hedra import HedraProvider
from .replicate_sadtalker import ReplicateSadTalkerProvider


def get_provider(name: str = "hedra", **kwargs) -> TalkingHeadProvider:
    """Return a talking head provider by name.

    Args:
        name: Provider name ("hedra" or "replicate").
        **kwargs: Provider-specific options (e.g. api_key).

    Returns:
        A provider implementing TalkingHeadProvider.

    Raises:
        ValueError: If the provider name is unknown.
    """
    if name == "hedra":
        return HedraProvider(api_key=kwargs.get("api_key", ""))
    if name == "replicate":
        return ReplicateSadTalkerProvider(api_key=kwargs.get("api_key", ""))
    raise ValueError(f"Unknown provider '{name}'. Available: hedra, replicate")


__all__ = ["get_provider", "HedraProvider", "ReplicateSadTalkerProvider"]
