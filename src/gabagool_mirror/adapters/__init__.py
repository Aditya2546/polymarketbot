"""Adapters for external services."""

from .base import BaseAdapter, AdapterConfig
from .polymarket_adapter import PolymarketAdapter
from .kalshi_adapter import KalshiAdapter

__all__ = [
    "BaseAdapter",
    "AdapterConfig",
    "PolymarketAdapter",
    "KalshiAdapter",
]

