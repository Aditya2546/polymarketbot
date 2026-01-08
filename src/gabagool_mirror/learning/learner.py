"""
Online Learner - Safe parameter optimization.

Uses contextual bandit / online ridge regression to tune:
- MIN_MAPPING_CONFIDENCE
- SLIPPAGE_BPS_BUFFER
- MAX_QTY_SCALE

With hard safety bounds to prevent catastrophic settings.
"""

import numpy as np
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import deque

from ..config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class LearnerConfig:
    """Configuration for online learner."""
    # Exploration
    epsilon: float = 0.1  # Exploration rate
    
    # Safety bounds
    min_mapping_confidence_bounds: Tuple[float, float] = (0.5, 0.95)
    slippage_bps_buffer_bounds: Tuple[int, int] = (10, 200)
    max_qty_scale_bounds: Tuple[float, float] = (0.1, 1.0)
    
    # Learning rate
    learning_rate: float = 0.01
    
    # History
    max_history: int = 1000
    
    # Circuit breaker
    max_consecutive_losses: int = 5
    max_drawdown_pct: float = 0.20


@dataclass
class TradeOutcome:
    """Outcome of a trade for learning."""
    timestamp: datetime
    
    # Context features
    spread_bps: float
    depth: float
    volatility: float
    time_to_expiry_minutes: float
    recent_fill_rate: float
    recent_slippage_bps: float
    
    # Action taken
    mapping_confidence: float
    slippage_buffer_bps: int
    qty_scale: float
    
    # Outcome
    filled: bool
    slippage_realized_bps: float
    pnl: float


class OnlineLearner:
    """
    Online learning for parameter optimization.
    
    Uses epsilon-greedy contextual bandit with safety bounds.
    Falls back to conservative defaults on circuit breaker.
    """
    
    def __init__(self, config: Optional[LearnerConfig] = None):
        """
        Initialize learner.
        
        Args:
            config: Learner configuration
        """
        self.config = config or LearnerConfig()
        
        settings = get_settings()
        
        # Current parameters
        self.min_mapping_confidence = settings.min_mapping_confidence
        self.slippage_bps_buffer = settings.slippage_bps_buffer
        self.max_qty_scale = settings.max_qty_scale
        
        # Conservative defaults for fallback
        self.default_min_mapping_confidence = 0.8
        self.default_slippage_bps_buffer = 75
        self.default_max_qty_scale = 0.3
        
        # History
        self.outcomes: deque = deque(maxlen=self.config.max_history)
        
        # Ridge regression weights (feature_dim x num_arms)
        # Features: [spread, depth, vol, time, fill_rate, slip, 1 (bias)]
        self.feature_dim = 7
        self.num_arms = 3  # [confidence, slippage, scale]
        
        # Initialize weights
        self.weights = np.zeros((self.feature_dim, self.num_arms))
        self.weight_covariance = [np.eye(self.feature_dim) for _ in range(self.num_arms)]
        
        # Performance tracking
        self.total_pnl = 0.0
        self.peak_pnl = 0.0
        self.consecutive_losses = 0
        self.circuit_breaker_active = False
        
        # Stats
        self.explorations = 0
        self.exploitations = 0
    
    def get_features(
        self,
        spread_bps: float,
        depth: float,
        volatility: float,
        time_to_expiry_minutes: float,
        recent_fill_rate: float,
        recent_slippage_bps: float
    ) -> np.ndarray:
        """
        Extract normalized features.
        """
        return np.array([
            spread_bps / 100,  # Normalize to ~[0, 1]
            min(depth / 1000, 1.0),  # Cap depth
            volatility * 100,  # Scale volatility
            time_to_expiry_minutes / 60,  # Hours
            recent_fill_rate,  # Already [0, 1]
            recent_slippage_bps / 100,  # Normalize
            1.0  # Bias
        ])
    
    def get_action(
        self,
        spread_bps: float,
        depth: float,
        volatility: float,
        time_to_expiry_minutes: float,
        recent_fill_rate: float,
        recent_slippage_bps: float
    ) -> Tuple[float, int, float]:
        """
        Get action (parameters) for current context.
        
        Returns:
            (min_mapping_confidence, slippage_bps_buffer, max_qty_scale)
        """
        # If circuit breaker is active, return conservative defaults
        if self.circuit_breaker_active:
            logger.warning("Circuit breaker active - using conservative defaults")
            return (
                self.default_min_mapping_confidence,
                self.default_slippage_bps_buffer,
                self.default_max_qty_scale
            )
        
        features = self.get_features(
            spread_bps, depth, volatility,
            time_to_expiry_minutes, recent_fill_rate, recent_slippage_bps
        )
        
        # Epsilon-greedy exploration
        if np.random.random() < self.config.epsilon:
            self.explorations += 1
            return self._explore()
        
        self.exploitations += 1
        
        # Exploit: use learned weights
        predictions = features @ self.weights
        
        # Map predictions to bounded parameters
        confidence = self._bound_value(
            predictions[0],
            self.config.min_mapping_confidence_bounds
        )
        
        slippage = int(self._bound_value(
            predictions[1] * 100,  # Scale back
            self.config.slippage_bps_buffer_bounds
        ))
        
        scale = self._bound_value(
            predictions[2],
            self.config.max_qty_scale_bounds
        )
        
        return confidence, slippage, scale
    
    def _explore(self) -> Tuple[float, int, float]:
        """
        Random exploration within bounds.
        """
        confidence = np.random.uniform(
            self.config.min_mapping_confidence_bounds[0],
            self.config.min_mapping_confidence_bounds[1]
        )
        
        slippage = np.random.randint(
            self.config.slippage_bps_buffer_bounds[0],
            self.config.slippage_bps_buffer_bounds[1] + 1
        )
        
        scale = np.random.uniform(
            self.config.max_qty_scale_bounds[0],
            self.config.max_qty_scale_bounds[1]
        )
        
        return confidence, slippage, scale
    
    def _bound_value(self, value: float, bounds: Tuple[float, float]) -> float:
        """Clamp value to bounds."""
        return max(bounds[0], min(bounds[1], value))
    
    def record_outcome(self, outcome: TradeOutcome) -> None:
        """
        Record a trade outcome for learning.
        
        Args:
            outcome: Trade outcome
        """
        self.outcomes.append(outcome)
        
        # Update PnL tracking
        self.total_pnl += outcome.pnl
        self.peak_pnl = max(self.peak_pnl, self.total_pnl)
        
        # Update consecutive losses
        if outcome.pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
        
        # Check circuit breaker conditions
        drawdown = (self.peak_pnl - self.total_pnl) / self.peak_pnl if self.peak_pnl > 0 else 0
        
        if (self.consecutive_losses >= self.config.max_consecutive_losses or
            drawdown >= self.config.max_drawdown_pct):
            
            if not self.circuit_breaker_active:
                logger.warning(
                    f"CIRCUIT BREAKER TRIGGERED: "
                    f"consecutive_losses={self.consecutive_losses}, "
                    f"drawdown={drawdown:.1%}"
                )
                self.circuit_breaker_active = True
                self._revert_to_defaults()
        
        # Update weights using online ridge regression
        self._update_weights(outcome)
    
    def _update_weights(self, outcome: TradeOutcome) -> None:
        """
        Update weights using online ridge regression.
        """
        features = self.get_features(
            outcome.spread_bps,
            outcome.depth,
            outcome.volatility,
            outcome.time_to_expiry_minutes,
            outcome.recent_fill_rate,
            outcome.recent_slippage_bps
        )
        
        # Reward signal: PnL normalized + fill bonus
        reward = outcome.pnl / 10  # Scale PnL
        if outcome.filled:
            reward += 0.1  # Small bonus for fills
        reward -= outcome.slippage_realized_bps / 1000  # Penalty for slippage
        
        # Target actions
        targets = np.array([
            outcome.mapping_confidence,
            outcome.slippage_buffer_bps / 100,  # Normalize
            outcome.qty_scale
        ])
        
        # Online update for each arm
        for arm in range(self.num_arms):
            # Sherman-Morrison update for covariance
            cov = self.weight_covariance[arm]
            cov_f = cov @ features
            denom = 1 + features @ cov_f
            self.weight_covariance[arm] = cov - np.outer(cov_f, cov_f) / denom
            
            # Weight update
            prediction = features @ self.weights[:, arm]
            error = reward * targets[arm] - prediction
            self.weights[:, arm] += self.config.learning_rate * error * features
    
    def _revert_to_defaults(self) -> None:
        """Revert to conservative defaults."""
        self.min_mapping_confidence = self.default_min_mapping_confidence
        self.slippage_bps_buffer = self.default_slippage_bps_buffer
        self.max_qty_scale = self.default_max_qty_scale
    
    def reset_circuit_breaker(self) -> None:
        """Manually reset circuit breaker after review."""
        logger.info("Circuit breaker reset")
        self.circuit_breaker_active = False
        self.consecutive_losses = 0
    
    def get_stats(self) -> dict:
        """Get learner statistics."""
        recent_outcomes = list(self.outcomes)[-100:]
        recent_pnl = sum(o.pnl for o in recent_outcomes) if recent_outcomes else 0
        recent_fill_rate = sum(1 for o in recent_outcomes if o.filled) / len(recent_outcomes) if recent_outcomes else 0
        
        return {
            "total_outcomes": len(self.outcomes),
            "total_pnl": self.total_pnl,
            "peak_pnl": self.peak_pnl,
            "current_drawdown": (self.peak_pnl - self.total_pnl) / self.peak_pnl if self.peak_pnl > 0 else 0,
            "consecutive_losses": self.consecutive_losses,
            "circuit_breaker_active": self.circuit_breaker_active,
            "explorations": self.explorations,
            "exploitations": self.exploitations,
            "exploration_rate": self.explorations / (self.explorations + self.exploitations) if (self.explorations + self.exploitations) > 0 else 0,
            "recent_100_pnl": recent_pnl,
            "recent_100_fill_rate": recent_fill_rate,
            "current_params": {
                "min_mapping_confidence": self.min_mapping_confidence,
                "slippage_bps_buffer": self.slippage_bps_buffer,
                "max_qty_scale": self.max_qty_scale
            }
        }

