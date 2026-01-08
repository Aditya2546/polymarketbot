"""
Signal Deduplication - Ensures idempotent processing of gabagool trades.

Uses both in-memory cache and database persistence to prevent
duplicate signal processing across restarts.
"""

import asyncio
from typing import Dict, Optional, Set
from datetime import datetime
import logging

from .signal import CopySignal

logger = logging.getLogger(__name__)


class SignalDeduplicator:
    """
    Ensures signals are processed exactly once.
    
    Maintains:
    - In-memory set for fast lookups
    - Database cursor for persistence across restarts
    - Sliding window to prevent unbounded memory growth
    """
    
    MAX_MEMORY_SIZE = 10000  # Max signals to keep in memory
    
    def __init__(self, repository=None):
        """
        Initialize deduplicator.
        
        Args:
            repository: Database repository for persistence (optional)
        """
        self._seen: Set[str] = set()
        self._seen_order: list = []  # For LRU eviction
        self._repository = repository
        self._last_cursor_ts: int = 0
        self._lock = asyncio.Lock()
        self._initialized = False
    
    async def initialize(self) -> None:
        """
        Initialize from database.
        
        Loads previously processed signal IDs and cursor position.
        """
        if self._initialized:
            return
        
        async with self._lock:
            if self._repository:
                try:
                    # Load last N processed signal IDs
                    recent_signals = await self._repository.get_recent_signal_ids(
                        limit=self.MAX_MEMORY_SIZE
                    )
                    self._seen = set(recent_signals)
                    self._seen_order = list(recent_signals)
                    
                    # Load cursor position
                    cursor = await self._repository.get_cursor("gabagool_trade_ts")
                    if cursor:
                        self._last_cursor_ts = cursor
                    
                    logger.info(
                        f"Deduplicator initialized: {len(self._seen)} signals, "
                        f"cursor at {self._last_cursor_ts}"
                    )
                except Exception as e:
                    logger.error(f"Failed to initialize deduplicator from DB: {e}")
            
            self._initialized = True
    
    async def is_duplicate(self, signal: CopySignal) -> bool:
        """
        Check if a signal has already been processed.
        
        Args:
            signal: CopySignal to check
            
        Returns:
            True if duplicate, False if new
        """
        if not self._initialized:
            await self.initialize()
        
        return signal.signal_id in self._seen
    
    async def mark_processed(self, signal: CopySignal) -> None:
        """
        Mark a signal as processed.
        
        Updates both memory and database.
        
        Args:
            signal: CopySignal that was processed
        """
        async with self._lock:
            # Add to memory
            if signal.signal_id not in self._seen:
                self._seen.add(signal.signal_id)
                self._seen_order.append(signal.signal_id)
                
                # Evict oldest if at capacity
                while len(self._seen) > self.MAX_MEMORY_SIZE:
                    oldest = self._seen_order.pop(0)
                    self._seen.discard(oldest)
            
            # Update cursor if this signal is newer
            if signal.ts_ms > self._last_cursor_ts:
                self._last_cursor_ts = signal.ts_ms
            
            # Persist to database
            if self._repository:
                try:
                    await self._repository.mark_signal_processed(signal.signal_id)
                    await self._repository.update_cursor("gabagool_trade_ts", self._last_cursor_ts)
                except Exception as e:
                    logger.error(f"Failed to persist signal processing: {e}")
    
    async def get_cursor(self) -> int:
        """Get the current cursor timestamp."""
        if not self._initialized:
            await self.initialize()
        return self._last_cursor_ts
    
    async def set_cursor(self, ts_ms: int) -> None:
        """Set the cursor timestamp."""
        async with self._lock:
            self._last_cursor_ts = ts_ms
            if self._repository:
                await self._repository.update_cursor("gabagool_trade_ts", ts_ms)
    
    def clear_memory(self) -> None:
        """Clear in-memory cache (does not affect database)."""
        self._seen.clear()
        self._seen_order.clear()
    
    @property
    def memory_size(self) -> int:
        """Current number of signals in memory."""
        return len(self._seen)

