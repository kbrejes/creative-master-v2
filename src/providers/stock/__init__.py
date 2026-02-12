"""Stock asset providers."""

from src.providers.stock.protocol import (
    StockProviderProtocol,
    StockRequest,
    StockResponse,
)

__all__ = [
    "StockProviderProtocol",
    "StockRequest",
    "StockResponse",
]
