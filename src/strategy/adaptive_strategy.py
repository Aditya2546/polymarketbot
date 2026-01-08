"""
Adaptive BTC 15-min Strategy

Improvements over the basic strategies:
1. Adapts to recent performance - reduces aggression after losses
2. Uses shorter momentum windows for faster trend detection
3. Detects trend reversals using divergence signals
4. Hedges when uncertain (like gabagool22)
5. Has circuit breakers for consecutive losses
6. Uses volatility-adjusted position sizing
"""

import numpy as np
from typing import Tuple, Dict, Optional, List
from datetime import datetime
from collections import deque


class AdaptiveStrategy:
    """
    Smart adaptive strategy for BTC 15-minute markets.
    """
    
    def __init__(self):
        self.name = "Adaptive Smart Strategy"
        
        # Track recent performance
        self.recent_trades: deque = deque(maxlen=20)  # Last 20 trades
        self.consecutive_losses = 0
        self.consecutive_wins = 0
        
        # Adaptive parameters
        self.base_confidence_threshold = 0.03
        self.base_edge_threshold = 0.02
        
        # Circuit breakers
        self.max_consecutive_losses = 4
        self.cooldown_until = None
        
        # Recent predictions for divergence detection
        self.recent_predictions: deque = deque(maxlen=10)
    
    def record_result(self, won: bool, pnl: float):
        """Record trade result for adaptation."""
        self.recent_trades.append({
            'won': won,
            'pnl': pnl,
            'timestamp': datetime.now()
        })
        
        if won:
            self.consecutive_wins += 1
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
            self.consecutive_wins = 0
            
            # Circuit breaker
            if self.consecutive_losses >= self.max_consecutive_losses:
                self.cooldown_until = datetime.now()
    
    def get_recent_win_rate(self) -> float:
        """Get win rate from recent trades."""
        if not self.recent_trades:
            return 0.5
        wins = sum(1 for t in self.recent_trades if t['won'])
        return wins / len(self.recent_trades)
    
    def get_adaptation_factor(self) -> float:
        """
        Returns a factor 0.5-1.5 based on recent performance.
        < 1 means be more conservative
        > 1 means be more aggressive
        """
        win_rate = self.get_recent_win_rate()
        
        if win_rate > 0.6:
            return 1.2  # Winning - be slightly more aggressive
        elif win_rate < 0.4:
            return 0.6  # Losing - be more conservative
        else:
            return 1.0  # Neutral
    
    def detect_trend_reversal(self, prices: np.ndarray) -> bool:
        """
        Detect if a trend reversal is likely.
        Uses price divergence and momentum exhaustion.
        """
        if len(prices) < 30:
            return False
        
        # Compare short vs medium momentum
        short_mom = (prices[-1] - prices[-5]) / prices[-5]
        med_mom = (prices[-1] - prices[-15]) / prices[-15]
        
        # Divergence: short momentum opposite to medium
        divergence = (short_mom > 0 and med_mom < 0) or (short_mom < 0 and med_mom > 0)
        
        # Momentum exhaustion: direction same but weakening
        if len(prices) >= 20:
            prev_short_mom = (prices[-5] - prices[-10]) / prices[-10]
            exhaustion = abs(short_mom) < abs(prev_short_mom) * 0.5
        else:
            exhaustion = False
        
        return divergence or exhaustion
    
    def calculate_volatility(self, prices: np.ndarray) -> float:
        """Calculate recent volatility."""
        if len(prices) < 10:
            return 0.001
        recent = prices[-30:] if len(prices) >= 30 else prices
        if len(recent) < 2:
            return 0.001
        returns = np.diff(recent) / recent[:-1]
        return np.std(returns)
    
    def predict(self, prices: List[float], baseline: float, 
                market_price_yes: float = 0.5) -> Tuple[Optional[str], float, float, Dict]:
        """
        Generate prediction with adaptive logic.
        
        Returns: (side, size_multiplier, edge, metadata)
        - side: "YES", "NO", "HEDGE", or None
        - size_multiplier: 0.0-1.0 position size factor
        - edge: detected edge
        - metadata: additional info
        """
        if len(prices) < 60:
            return None, 0, 0, {'reason': 'insufficient_data'}
        
        # Check circuit breaker
        if self.cooldown_until:
            since_cooldown = (datetime.now() - self.cooldown_until).seconds
            if since_cooldown < 300:  # 5 min cooldown
                return None, 0, 0, {'reason': 'circuit_breaker', 'cooldown_remaining': 300 - since_cooldown}
            else:
                self.cooldown_until = None
                self.consecutive_losses = 0
        
        prices = np.array(prices)
        current = prices[-1]
        
        # === SIGNAL CALCULATION ===
        
        # 1. Multi-timeframe momentum
        mom_1min = (current - prices[-2]) / prices[-2] if len(prices) >= 2 else 0
        mom_3min = (current - prices[-4]) / prices[-4] if len(prices) >= 4 else 0
        mom_5min = (current - prices[-6]) / prices[-6] if len(prices) >= 6 else 0
        mom_10min = (current - prices[-11]) / prices[-11] if len(prices) >= 11 else 0
        
        # Weighted momentum signal
        momentum = (0.4 * mom_1min + 0.3 * mom_3min + 0.2 * mom_5min + 0.1 * mom_10min)
        
        # 2. Distance from baseline (mean reversion)
        baseline_gap = (current - baseline) / baseline
        
        # 3. Trend consistency
        up_moves = sum(1 for i in range(-10, 0) if prices[i] > prices[i-1])
        trend_consistency = (up_moves - 5) / 5  # -1 to +1
        
        # 4. Volatility
        volatility = self.calculate_volatility(prices)
        vol_regime = "high" if volatility > 0.002 else "low" if volatility < 0.0005 else "normal"
        
        # 5. Reversal detection
        reversal_likely = self.detect_trend_reversal(prices)
        
        # === PROBABILITY CALCULATION ===
        
        p_yes = 0.5
        
        # Momentum contribution
        p_yes += momentum * 100  # Scale momentum to probability
        
        # Trend contribution
        p_yes += trend_consistency * 0.1
        
        # Mean reversion (if extended)
        if abs(baseline_gap) > 0.002:  # >0.2% from baseline
            # Expect reversion
            p_yes -= baseline_gap * 10
        
        # Reversal adjustment
        if reversal_likely:
            # Reduce confidence in current direction
            p_yes = 0.5 + (p_yes - 0.5) * 0.5
        
        # Volatility dampening
        if vol_regime == "high":
            p_yes = 0.5 + (p_yes - 0.5) * 0.7
        
        # Clamp
        p_yes = np.clip(p_yes, 0.15, 0.85)
        p_no = 1 - p_yes
        
        # === EDGE CALCULATION ===
        
        market_price_no = 1 - market_price_yes
        
        edge_yes = p_yes - market_price_yes
        edge_no = p_no - market_price_no
        
        # === DECISION LOGIC ===
        
        confidence = abs(p_yes - 0.5)
        adaptation = self.get_adaptation_factor()
        
        # Adjusted thresholds
        conf_threshold = self.base_confidence_threshold / adaptation
        edge_threshold = self.base_edge_threshold / adaptation
        
        metadata = {
            'p_yes': p_yes,
            'p_no': p_no,
            'momentum': momentum,
            'baseline_gap': baseline_gap,
            'trend_consistency': trend_consistency,
            'volatility': volatility,
            'vol_regime': vol_regime,
            'reversal_likely': reversal_likely,
            'adaptation_factor': adaptation,
            'recent_win_rate': self.get_recent_win_rate(),
            'consecutive_losses': self.consecutive_losses
        }
        
        # Decision
        if confidence < conf_threshold:
            # Low confidence - consider hedging or skip
            if vol_regime == "high" and abs(baseline_gap) < 0.001:
                return "HEDGE", 0.3, 0, {**metadata, 'action': 'hedge_uncertain'}
            return None, 0, 0, {**metadata, 'action': 'skip_low_confidence'}
        
        # Determine side
        if edge_yes > edge_no and edge_yes > edge_threshold:
            side = "YES"
            edge = edge_yes
        elif edge_no > edge_yes and edge_no > edge_threshold:
            side = "NO"
            edge = edge_no
        else:
            return None, 0, 0, {**metadata, 'action': 'skip_no_edge'}
        
        # Position size multiplier (0.3 to 1.0)
        size_mult = min(1.0, 0.3 + (edge / 0.2) * 0.7)
        size_mult *= adaptation  # Reduce if losing
        size_mult = np.clip(size_mult, 0.2, 1.0)
        
        # Extra caution after losses
        if self.consecutive_losses >= 2:
            size_mult *= 0.5
        
        metadata['action'] = 'trade'
        metadata['side'] = side
        metadata['edge'] = edge
        metadata['size_mult'] = size_mult
        
        return side, size_mult, edge, metadata


# Singleton instance
_strategy_instance = None

def get_adaptive_strategy() -> AdaptiveStrategy:
    global _strategy_instance
    if _strategy_instance is None:
        _strategy_instance = AdaptiveStrategy()
    return _strategy_instance

