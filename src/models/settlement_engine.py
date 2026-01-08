"""Settlement window engine for computing avg60."""

import time
from typing import Dict, Optional, Tuple
import numpy as np

from ..data.brti_feed import BRTIFeed, PriceTick
from ..logger import StructuredLogger


class SettlementEngine:
    """Settlement window engine.
    
    Computes 60-second average aligned to settlement rules.
    Supports multiple conventions and logs both for comparison.
    """
    
    def __init__(
        self,
        brti_feed: BRTIFeed,
        convention: str = "A",
        log_both: bool = True
    ):
        """Initialize settlement engine.
        
        Args:
            brti_feed: BRTI feed instance
            convention: Settlement convention ("A" or "B")
            log_both: Whether to log both conventions
        """
        self.brti_feed = brti_feed
        self.convention = convention
        self.log_both = log_both
        
        # Current state
        self.avg60_a: Optional[float] = None  # [T-60, T-1]
        self.avg60_b: Optional[float] = None  # (T-60, T]
        self.last_update: Optional[float] = None
        
        # Logging
        self.logger = StructuredLogger(__name__)
    
    def compute_avg60_for_timestamp(
        self,
        settle_timestamp: float,
        convention: Optional[str] = None
    ) -> Optional[float]:
        """Compute 60-second average for specific settlement timestamp.
        
        Args:
            settle_timestamp: Settlement timestamp (Unix seconds)
            convention: Convention to use (None = use default)
            
        Returns:
            60-second average or None if insufficient data
        """
        if convention is None:
            convention = self.convention
        
        if convention == "A":
            # [T-60, T-1]: exclusive of settle moment
            start_time = settle_timestamp - 60
            end_time = settle_timestamp - 1
        else:  # convention == "B"
            # (T-60, T]: inclusive of settle moment
            start_time = settle_timestamp - 60
            end_time = settle_timestamp
        
        return self.brti_feed.compute_simple_average(start_time, end_time)
    
    def compute_rolling_avg60(self) -> Tuple[Optional[float], Optional[float]]:
        """Compute rolling 60-second averages (both conventions).
        
        Returns:
            Tuple of (avg60_a, avg60_b) or (None, None) if insufficient data
        """
        current_time = time.time()
        
        # Convention A: [T-60, T-1]
        avg60_a = self.brti_feed.compute_simple_average(
            current_time - 60,
            current_time - 1
        )
        
        # Convention B: (T-60, T]
        avg60_b = self.brti_feed.compute_simple_average(
            current_time - 60,
            current_time
        )
        
        return avg60_a, avg60_b
    
    def update(self) -> None:
        """Update rolling averages."""
        self.avg60_a, self.avg60_b = self.compute_rolling_avg60()
        self.last_update = time.time()
        
        if self.log_both and self.avg60_a is not None and self.avg60_b is not None:
            diff = abs(self.avg60_a - self.avg60_b)
            self.logger.debug(
                "Updated avg60",
                avg60_a=self.avg60_a,
                avg60_b=self.avg60_b,
                diff=diff
            )
    
    def get_current_avg60(self) -> Optional[float]:
        """Get current 60-second average using configured convention.
        
        Returns:
            Current avg60 or None
        """
        if self.convention == "A":
            return self.avg60_a
        else:
            return self.avg60_b
    
    def get_both_avg60(self) -> Tuple[Optional[float], Optional[float]]:
        """Get both avg60 values.
        
        Returns:
            Tuple of (avg60_a, avg60_b)
        """
        return self.avg60_a, self.avg60_b
    
    def compute_distance_to_threshold(
        self,
        baseline: float,
        threshold_offset: float = 0.0
    ) -> Optional[float]:
        """Compute distance from current avg60 to settlement threshold.
        
        Args:
            baseline: Baseline price (start reference)
            threshold_offset: Additional offset for threshold (e.g., minimal tick)
            
        Returns:
            Distance in USD (positive = above threshold, negative = below)
        """
        avg60 = self.get_current_avg60()
        
        if avg60 is None:
            return None
        
        threshold = baseline + threshold_offset
        return avg60 - threshold
    
    def compute_max_movement_bounds(
        self,
        seconds_remaining: float,
        current_avg60: float,
        volatility_per_second: float
    ) -> Tuple[float, float]:
        """Compute theoretical bounds for avg60 movement.
        
        Given remaining time and volatility, compute how much avg60 could
        theoretically move in best/worst case.
        
        Args:
            seconds_remaining: Seconds until settlement
            current_avg60: Current 60-second average
            volatility_per_second: 1-second return volatility
            
        Returns:
            Tuple of (min_possible_avg60, max_possible_avg60)
        """
        # This is conservative: assume price could move by N standard deviations
        # in the remaining time
        
        # Use 3-sigma bound
        sigma_multiplier = 3.0
        
        # Maximum change in avg60 depends on:
        # 1. How many seconds will be replaced in the rolling window
        # 2. How much price could move in those seconds
        
        # Simplified: if we have S seconds remaining, worst case is price
        # moves immediately and stays there, affecting up to min(S, 60) samples
        samples_affected = min(seconds_remaining, 60)
        
        # Maximum price movement in remaining time
        price_volatility = current_avg60 * volatility_per_second * np.sqrt(seconds_remaining)
        max_price_move = sigma_multiplier * price_volatility
        
        # Impact on avg60 is proportional to fraction of samples affected
        impact_fraction = samples_affected / 60
        max_avg60_move = max_price_move * impact_fraction
        
        min_possible = current_avg60 - max_avg60_move
        max_possible = current_avg60 + max_avg60_move
        
        return min_possible, max_possible
    
    def is_outcome_locked(
        self,
        baseline: float,
        seconds_remaining: float,
        volatility_per_second: float,
        lock_probability: float = 0.99
    ) -> Optional[str]:
        """Check if outcome is effectively locked.
        
        Args:
            baseline: Baseline price
            seconds_remaining: Seconds until settlement
            volatility_per_second: 1-second return volatility
            lock_probability: Probability threshold for "locked"
            
        Returns:
            "YES" if locked YES, "NO" if locked NO, None if not locked
        """
        current_avg60 = self.get_current_avg60()
        
        if current_avg60 is None:
            return None
        
        # Compute bounds
        min_possible, max_possible = self.compute_max_movement_bounds(
            seconds_remaining,
            current_avg60,
            volatility_per_second
        )
        
        # Check if bounds don't cross threshold
        if min_possible > baseline:
            # Locked YES (cannot go below baseline)
            return "YES"
        elif max_possible < baseline:
            # Locked NO (cannot go above baseline)
            return "NO"
        
        return None
    
    def get_status(self) -> Dict:
        """Get settlement engine status.
        
        Returns:
            Status dictionary
        """
        return {
            "convention": self.convention,
            "avg60_a": self.avg60_a,
            "avg60_b": self.avg60_b,
            "last_update": self.last_update,
            "feed_ready": self.brti_feed.is_ready()
        }

