"""Probability model with Monte Carlo simulation."""

import time
from typing import Dict, Optional, Tuple
import numpy as np
from numba import jit

from ..data.brti_feed import BRTIFeed
from ..models.settlement_engine import SettlementEngine
from ..logger import StructuredLogger


@jit(nopython=True)
def simulate_price_paths(
    current_price: float,
    num_steps: int,
    num_sims: int,
    volatility_per_second: float,
    random_seed: int
) -> np.ndarray:
    """Simulate price paths using geometric Brownian motion.
    
    Optimized with Numba for speed.
    
    Args:
        current_price: Starting price
        num_steps: Number of time steps
        num_sims: Number of simulations
        volatility_per_second: 1-second return volatility
        random_seed: Random seed for reproducibility
        
    Returns:
        Array of shape (num_sims, num_steps) with price paths
    """
    np.random.seed(random_seed)
    
    # Initialize price paths
    paths = np.zeros((num_sims, num_steps))
    paths[:, 0] = current_price
    
    # Generate random returns
    returns = np.random.normal(0, volatility_per_second, (num_sims, num_steps - 1))
    
    # Simulate paths
    for i in range(num_sims):
        for t in range(1, num_steps):
            # Geometric Brownian motion: P(t+1) = P(t) * exp(return)
            paths[i, t] = paths[i, t-1] * np.exp(returns[i, t-1])
    
    return paths


class ProbabilityModel:
    """Probability model for computing P(YES) using Monte Carlo simulation."""
    
    def __init__(
        self,
        brti_feed: BRTIFeed,
        settlement_engine: SettlementEngine,
        num_simulations: int = 10000,
        volatility_window: int = 180,
        random_seed: int = 42
    ):
        """Initialize probability model.
        
        Args:
            brti_feed: BRTI feed instance
            settlement_engine: Settlement engine instance
            num_simulations: Number of Monte Carlo simulations
            volatility_window: Window for volatility estimation (seconds)
            random_seed: Random seed for reproducibility
        """
        self.brti_feed = brti_feed
        self.settlement_engine = settlement_engine
        self.num_simulations = num_simulations
        self.volatility_window = volatility_window
        self.random_seed = random_seed
        
        # Current state
        self.p_yes: Optional[float] = None
        self.p_no: Optional[float] = None
        self.volatility: Optional[float] = None
        self.last_update: Optional[float] = None
        
        # Logging
        self.logger = StructuredLogger(__name__)
    
    def estimate_volatility(self) -> Optional[float]:
        """Estimate 1-second return volatility from recent price history.
        
        Returns:
            Volatility (standard deviation of 1-second returns) or None
        """
        # Get price history
        ticks = self.brti_feed.get_price_history(duration_seconds=self.volatility_window)
        
        if len(ticks) < 60:
            return None
        
        # Extract prices and timestamps
        prices = np.array([tick.price for tick in ticks])
        timestamps = np.array([tick.timestamp for tick in ticks])
        
        # Compute log returns
        log_returns = np.diff(np.log(prices))
        time_diffs = np.diff(timestamps)
        
        # Normalize returns to 1-second intervals
        # return_per_second = log_return / sqrt(time_diff)
        returns_per_second = log_returns / np.sqrt(time_diffs)
        
        # Compute standard deviation
        volatility = np.std(returns_per_second)
        
        return float(volatility)
    
    def compute_probability(
        self,
        baseline: float,
        settle_timestamp: float,
        deterministic_threshold_seconds: int = 10,
        deterministic_lock_prob: float = 0.99
    ) -> Tuple[Optional[float], Optional[float]]:
        """Compute P(YES) and P(NO) for settlement.
        
        Args:
            baseline: Baseline price (threshold)
            settle_timestamp: Settlement timestamp (Unix seconds)
            deterministic_threshold_seconds: Use deterministic bounds if time < this
            deterministic_lock_prob: Probability threshold for deterministic lock
            
        Returns:
            Tuple of (p_yes, p_no) or (None, None) if cannot compute
        """
        # Check if we have current price and avg60
        current_price = self.brti_feed.get_current_price()
        current_avg60 = self.settlement_engine.get_current_avg60()
        
        if current_price is None or current_avg60 is None:
            return None, None
        
        # Compute time to settlement
        current_time = time.time()
        seconds_to_settle = settle_timestamp - current_time
        
        if seconds_to_settle <= 0:
            # Already settled - return deterministic outcome
            if current_avg60 > baseline:
                return 1.0, 0.0
            else:
                return 0.0, 1.0
        
        # Estimate volatility
        volatility = self.estimate_volatility()
        
        if volatility is None:
            self.logger.warning("Cannot estimate volatility - insufficient data")
            return None, None
        
        self.volatility = volatility
        
        # Check for deterministic lock near settlement
        if seconds_to_settle < deterministic_threshold_seconds:
            locked = self.settlement_engine.is_outcome_locked(
                baseline=baseline,
                seconds_remaining=seconds_to_settle,
                volatility_per_second=volatility,
                lock_probability=deterministic_lock_prob
            )
            
            if locked == "YES":
                self.logger.debug(
                    "Outcome locked to YES",
                    seconds_remaining=seconds_to_settle,
                    current_avg60=current_avg60,
                    baseline=baseline
                )
                return 0.99, 0.01
            elif locked == "NO":
                self.logger.debug(
                    "Outcome locked to NO",
                    seconds_remaining=seconds_to_settle,
                    current_avg60=current_avg60,
                    baseline=baseline
                )
                return 0.01, 0.99
        
        # Run Monte Carlo simulation
        p_yes = self._monte_carlo_simulation(
            current_price=current_price,
            current_avg60=current_avg60,
            baseline=baseline,
            seconds_to_settle=int(seconds_to_settle),
            volatility=volatility
        )
        
        p_no = 1.0 - p_yes
        
        return p_yes, p_no
    
    def _monte_carlo_simulation(
        self,
        current_price: float,
        current_avg60: float,
        baseline: float,
        seconds_to_settle: int,
        volatility: float
    ) -> float:
        """Run Monte Carlo simulation to compute P(YES).
        
        Args:
            current_price: Current BTC price
            current_avg60: Current 60-second average
            baseline: Baseline price (threshold)
            seconds_to_settle: Seconds until settlement
            volatility: 1-second return volatility
            
        Returns:
            Probability that final avg60 > baseline
        """
        # Simulate price paths from now until settlement
        num_steps = seconds_to_settle
        
        if num_steps < 1:
            # Too close to settlement, return current outcome
            return 1.0 if current_avg60 > baseline else 0.0
        
        # Generate price paths
        paths = simulate_price_paths(
            current_price=current_price,
            num_steps=num_steps + 1,  # +1 for current price
            num_sims=self.num_simulations,
            volatility_per_second=volatility,
            random_seed=self.random_seed
        )
        
        # For each simulation, compute what avg60 would be at settlement
        # This requires knowing the current 60-second window and simulating forward
        
        # Get current price buffer (last 60 seconds)
        current_buffer = self.brti_feed.get_price_history(duration_seconds=60)
        current_prices = np.array([tick.price for tick in current_buffer])
        
        # For each simulation, compute final avg60
        final_avg60s = np.zeros(self.num_simulations)
        
        for sim in range(self.num_simulations):
            # Combine current buffer with simulated future prices
            if seconds_to_settle >= 60:
                # After 60 seconds, avg60 is entirely from simulated prices
                # Take last 60 samples from simulation
                final_avg60s[sim] = np.mean(paths[sim, -60:])
            else:
                # Partial replacement of buffer
                # Keep (60 - seconds_to_settle) oldest prices, add simulated prices
                num_keep = 60 - seconds_to_settle
                if len(current_prices) >= num_keep:
                    old_prices = current_prices[:num_keep]
                else:
                    old_prices = current_prices
                
                new_prices = paths[sim, 1:]  # Skip initial price (current)
                combined = np.concatenate([old_prices, new_prices])
                
                # Take last 60 prices
                if len(combined) >= 60:
                    final_avg60s[sim] = np.mean(combined[-60:])
                else:
                    final_avg60s[sim] = np.mean(combined)
        
        # Compute P(YES) = fraction of simulations where final_avg60 > baseline
        p_yes = np.mean(final_avg60s > baseline)
        
        return float(p_yes)
    
    def update(
        self,
        baseline: float,
        settle_timestamp: float
    ) -> None:
        """Update probability estimates.
        
        Args:
            baseline: Baseline price
            settle_timestamp: Settlement timestamp
        """
        self.p_yes, self.p_no = self.compute_probability(baseline, settle_timestamp)
        self.last_update = time.time()
        
        if self.p_yes is not None:
            self.logger.debug(
                "Updated probabilities",
                p_yes=self.p_yes,
                p_no=self.p_no,
                volatility=self.volatility
            )
    
    def get_probabilities(self) -> Tuple[Optional[float], Optional[float]]:
        """Get current probability estimates.
        
        Returns:
            Tuple of (p_yes, p_no)
        """
        return self.p_yes, self.p_no
    
    def get_confidence(self) -> Optional[float]:
        """Get confidence in prediction (distance from 50-50).
        
        Returns:
            Confidence value (0 to 0.5) or None
        """
        if self.p_yes is None:
            return None
        
        return abs(self.p_yes - 0.5)
    
    def get_status(self) -> Dict:
        """Get model status.
        
        Returns:
            Status dictionary
        """
        return {
            "p_yes": self.p_yes,
            "p_no": self.p_no,
            "volatility": self.volatility,
            "confidence": self.get_confidence(),
            "last_update": self.last_update,
            "num_simulations": self.num_simulations
        }

