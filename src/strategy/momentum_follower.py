"""
Momentum Following Strategy

Waits 10 minutes into the 15-minute interval, then bets on continuation
in the same direction. This is a pure momentum/trend-following approach.
"""

import numpy as np
from typing import Optional, Tuple
from ..logger import StructuredLogger


class MomentumFollower:
    """
    Simple momentum-following strategy.
    
    Logic:
    1. Wait until 10 minutes into the 15-minute interval
    2. Check if price is UP or DOWN vs baseline
    3. Bet on continuation (YES if up, NO if down)
    4. Confidence based on momentum strength
    """
    
    def __init__(self, min_confidence: float = 0.02):
        self.name = "Momentum Follower (10min)"
        self.logger = StructuredLogger(__name__)
        self.min_confidence = min_confidence
    
    def predict(self, 
                current_price: float, 
                baseline: float,
                prices: list,
                minutes_elapsed: int = 10) -> Tuple[Optional[float], Optional[float], dict]:
        """
        Make prediction based on momentum at 10 minutes.
        
        Args:
            current_price: Current BTC price
            baseline: Starting price of 15-min interval
            prices: Recent price history
            minutes_elapsed: How many minutes into interval (should be ~10)
        
        Returns:
            (p_yes, p_no, metadata) tuple
        """
        if len(prices) < 60:
            return None, None, {}
        
        # Calculate current momentum vs baseline
        momentum = (current_price - baseline) / baseline
        
        # Calculate momentum strength over last few minutes
        prices_arr = np.array(prices)
        
        # Short-term momentum (last 5 minutes)
        if len(prices) >= 5:
            short_momentum = (current_price - prices_arr[-5]) / prices_arr[-5]
        else:
            short_momentum = momentum
        
        # Trend consistency
        recent = prices_arr[-30:]  # Last 30 seconds
        up_ticks = sum(1 for i in range(len(recent)-1) if recent[i+1] > recent[i])
        trend_strength = (up_ticks / (len(recent) - 1)) if len(recent) > 1 else 0.5
        
        # Calculate confidence based on momentum strength
        # Strong momentum = high confidence in continuation
        momentum_strength = abs(momentum)
        
        # Base probability on current direction
        if momentum > 0:
            # Currently UP vs baseline - bet YES (continuation up)
            base_prob = 0.50 + (momentum * 100)  # Scale momentum
            
            # Adjust based on trend consistency
            if trend_strength > 0.6:  # Strong uptrend
                base_prob += 0.05
            
            # Adjust based on short-term momentum alignment
            if short_momentum > 0:
                base_prob += 0.03
            else:
                base_prob -= 0.03  # Divergence reduces confidence
            
            p_yes = np.clip(base_prob, 0.05, 0.95)
            p_no = 1 - p_yes
            
        else:
            # Currently DOWN vs baseline - bet NO (continuation down)
            base_prob = 0.50 + (abs(momentum) * 100)  # Scale momentum
            
            # Adjust based on trend consistency
            if trend_strength < 0.4:  # Strong downtrend
                base_prob += 0.05
            
            # Adjust based on short-term momentum alignment
            if short_momentum < 0:
                base_prob += 0.03
            else:
                base_prob -= 0.03
            
            p_no = np.clip(base_prob, 0.05, 0.95)
            p_yes = 1 - p_no
        
        confidence = abs(p_yes - 0.5)
        
        metadata = {
            'momentum': momentum,
            'momentum_strength': momentum_strength,
            'short_momentum': short_momentum,
            'trend_strength': trend_strength,
            'direction': 'UP' if momentum > 0 else 'DOWN',
            'minutes_elapsed': minutes_elapsed
        }
        
        return p_yes, p_no, metadata
    
    def should_trade(self, confidence: float, edge: float, min_edge: float = 0.01) -> bool:
        """
        Decide if we should trade based on confidence and edge.
        
        Args:
            confidence: Prediction confidence
            edge: Calculated edge over market
            min_edge: Minimum edge threshold
        
        Returns:
            True if we should trade
        """
        return confidence >= self.min_confidence and edge >= min_edge
    
    def get_position_size(self, 
                         edge: float, 
                         balance: float, 
                         max_size: float = 15.0) -> float:
        """
        Calculate position size using Kelly Criterion.
        
        Args:
            edge: Calculated edge
            balance: Available balance
            max_size: Maximum position size
        
        Returns:
            Position size in dollars
        """
        # Kelly fraction
        kelly = edge / 0.5  # Assuming 50-50 odds base
        kelly = min(kelly, 0.25)  # Cap at 25%
        
        # Half-Kelly for safety
        size = balance * kelly * 0.5
        
        # Apply limits
        size = min(size, max_size, balance)
        size = max(size, 2.0)  # Minimum $2
        
        return size

