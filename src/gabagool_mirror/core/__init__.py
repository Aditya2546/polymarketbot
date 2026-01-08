"""Core types and utilities for Gabagool Mirror Bot."""

from .signal import CopySignal, SignalAction, SignalSide
from .mapping import MarketMapping, MappingResult
from .dedup import SignalDeduplicator

__all__ = [
    "CopySignal",
    "SignalAction", 
    "SignalSide",
    "MarketMapping",
    "MappingResult",
    "SignalDeduplicator",
]

