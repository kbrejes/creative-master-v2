"""Stock asset providers."""

from src.providers.providers.stock.protocol import (
    StockProviderProtocol,
    StockRequest,
    StockResponse,
)

__all__ = [
    "StockProviderProtocol",
    "StockRequest",
    "StockResponse",
]
