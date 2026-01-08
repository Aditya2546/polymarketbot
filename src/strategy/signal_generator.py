"""Signal generator for trade recommendations."""

import time
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

from ..data.kalshi_client import KalshiMarket
from ..data.brti_feed import BRTIFeed
from ..models.settlement_engine import SettlementEngine
from ..models.probability_model import ProbabilityModel
from ..models.edge_detector import EdgeDetector, EdgeMeasurement
from ..logger import StructuredLogger


@dataclass
class TradeSignal:
    """Trade signal recommendation."""
    
    timestamp: float
    market_id: str
    side: str  # "YES" or "NO"
    signal_type: str  # "delay_capture", "momentum", "baseline_gap"
    p_true: float
    p_market: float
    edge: float
    confidence: float
    recommended_size_usd: float
    reason: str
    metadata: Dict
    
    def __repr__(self) -> str:
        return (
            f"TradeSignal(side={self.side}, type={self.signal_type}, "
            f"edge={self.edge:.4f}, size=${self.recommended_size_usd:.2f})"
        )


class SignalGenerator:
    """Generate trade signals using multiple strategies."""
    
    def __init__(
        self,
        brti_feed: BRTIFeed,
        settlement_engine: SettlementEngine,
        probability_model: ProbabilityModel,
        edge_detector: EdgeDetector,
        enable_delay_capture: bool = True,
        enable_momentum: bool = True,
        enable_baseline_gap: bool = True,
        delay_weight: float = 1.0,
        momentum_weight: float = 0.5,
        baseline_gap_weight: float = 0.3,
        momentum_threshold: float = 0.002,
        baseline_gap_window: int = 30,
        neutral_zone_min: float = 0.45,
        neutral_zone_max: float = 0.55,
        final_window_seconds: int = 15,
        final_window_override_edge: float = 0.15,
        max_spread_pct: float = 0.05
    ):
        """Initialize signal generator.
        
        Args:
            brti_feed: BRTI feed instance
            settlement_engine: Settlement engine instance
            probability_model: Probability model instance
            edge_detector: Edge detector instance
            enable_delay_capture: Enable delay capture signals
            enable_momentum: Enable momentum signals
            enable_baseline_gap: Enable baseline gap signals
            delay_weight: Weight for delay signals
            momentum_weight: Weight for momentum signals
            baseline_gap_weight: Weight for baseline gap signals
            momentum_threshold: Minimum move for momentum signal
            baseline_gap_window: Window for baseline gap (seconds after open)
            neutral_zone_min: Min probability for neutral zone
            neutral_zone_max: Max probability for neutral zone
            final_window_seconds: No-trade window before settlement
            final_window_override_edge: Override edge for final window
            max_spread_pct: Maximum allowed spread
        """
        self.brti_feed = brti_feed
        self.settlement_engine = settlement_engine
        self.probability_model = probability_model
        self.edge_detector = edge_detector
        
        # Signal type enables
        self.enable_delay_capture = enable_delay_capture
        self.enable_momentum = enable_momentum
        self.enable_baseline_gap = enable_baseline_gap
        
        # Weights
        self.delay_weight = delay_weight
        self.momentum_weight = momentum_weight
        self.baseline_gap_weight = baseline_gap_weight
        
        # Thresholds
        self.momentum_threshold = momentum_threshold
        self.baseline_gap_window = baseline_gap_window
        self.neutral_zone_min = neutral_zone_min
        self.neutral_zone_max = neutral_zone_max
        self.final_window_seconds = final_window_seconds
        self.final_window_override_edge = final_window_override_edge
        self.max_spread_pct = max_spread_pct
        
        # State
        self.last_signal: Optional[TradeSignal] = None
        self.interval_start_price: Optional[float] = None
        self.interval_start_time: Optional[float] = None
        
        # Logging
        self.logger = StructuredLogger(__name__)
    
    def set_interval_start(self, price: float, timestamp: float) -> None:
        """Set interval start price and time.
        
        Args:
            price: Start price (baseline)
            timestamp: Start timestamp
        """
        self.interval_start_price = price
        self.interval_start_time = timestamp
        
        self.logger.info(
            "New interval started",
            baseline=price,
            timestamp=timestamp
        )
    
    def check_no_trade_conditions(
        self,
        market: KalshiMarket,
        settle_timestamp: float
    ) -> Optional[str]:
        """Check if no-trade conditions apply.
        
        Args:
            market: Market data
            settle_timestamp: Settlement timestamp
            
        Returns:
            Reason string if should not trade, None otherwise
        """
        # Check spread
        spread = market.get_spread()
        if spread is not None and spread > self.max_spread_pct:
            return f"Spread too wide: {spread:.1%} > {self.max_spread_pct:.1%}"
        
        # Check neutral zone
        p_yes, _ = self.probability_model.get_probabilities()
        if p_yes is not None:
            if self.neutral_zone_min <= p_yes <= self.neutral_zone_max:
                return f"In neutral zone: p_yes={p_yes:.3f}"
        
        # Check final window
        seconds_to_settle = settle_timestamp - time.time()
        if seconds_to_settle < self.final_window_seconds:
            # Allow override if edge is huge
            best_edge = self.edge_detector.get_best_edge()
            if best_edge is None or best_edge.edge_net < self.final_window_override_edge:
                return f"Too close to settlement: {seconds_to_settle:.1f}s"
        
        return None
    
    def detect_delay_capture(
        self,
        market: KalshiMarket
    ) -> Optional[Tuple[str, EdgeMeasurement, str]]:
        """Detect delay capture opportunity.
        
        Args:
            market: Market data
            
        Returns:
            Tuple of (side, edge_measurement, reason) or None
        """
        if not self.enable_delay_capture:
            return None
        
        signal = self.edge_detector.get_signal()
        
        if signal is None:
            return None
        
        side, edge_measurement = signal
        
        reason = (
            f"Delay capture: market lagging true probability by "
            f"{edge_measurement.edge_net:.1%}"
        )
        
        return side, edge_measurement, reason
    
    def detect_momentum(
        self,
        market: KalshiMarket,
        baseline: float
    ) -> Optional[Tuple[str, EdgeMeasurement, str]]:
        """Detect momentum confirmation opportunity.
        
        Args:
            market: Market data
            baseline: Baseline price
            
        Returns:
            Tuple of (side, edge_measurement, reason) or None
        """
        if not self.enable_momentum:
            return None
        
        # Get current price
        current_price = self.brti_feed.get_current_price()
        
        if current_price is None:
            return None
        
        # Compute move from baseline
        move = (current_price - baseline) / baseline
        
        if abs(move) < self.momentum_threshold:
            return None
        
        # Check if market underprices continuation
        p_yes, p_no = self.probability_model.get_probabilities()
        
        if p_yes is None or p_no is None:
            return None
        
        # If strong upward move and p_yes high, check market
        if move > 0 and p_yes > 0.6:
            edge_measurement = self.edge_detector.edge_yes
            if edge_measurement and edge_measurement.edge_net > 0:
                reason = f"Momentum up: {move:.2%} move, market underpricing"
                return "YES", edge_measurement, reason
        
        # If strong downward move and p_no high, check market
        elif move < 0 and p_no > 0.6:
            edge_measurement = self.edge_detector.edge_no
            if edge_measurement and edge_measurement.edge_net > 0:
                reason = f"Momentum down: {move:.2%} move, market underpricing"
                return "NO", edge_measurement, reason
        
        return None
    
    def detect_baseline_gap(
        self,
        market: KalshiMarket,
        baseline: float,
        settle_timestamp: float
    ) -> Optional[Tuple[str, EdgeMeasurement, str]]:
        """Detect baseline gap at interval open.
        
        Args:
            market: Market data
            baseline: Baseline price
            settle_timestamp: Settlement timestamp
            
        Returns:
            Tuple of (side, edge_measurement, reason) or None
        """
        if not self.enable_baseline_gap:
            return None
        
        if self.interval_start_time is None:
            return None
        
        # Check if we're still in the gap window
        time_since_start = time.time() - self.interval_start_time
        if time_since_start > self.baseline_gap_window:
            return None
        
        # Get current price
        current_price = self.brti_feed.get_current_price()
        
        if current_price is None:
            return None
        
        # Check if price already away from baseline
        distance = current_price - baseline
        distance_pct = distance / baseline
        
        if abs(distance_pct) < 0.001:  # Too close, no gap
            return None
        
        # Check if market has priced this in
        p_yes, p_no = self.probability_model.get_probabilities()
        
        if p_yes is None or p_no is None:
            return None
        
        if distance > 0:  # Price above baseline
            edge_measurement = self.edge_detector.edge_yes
            if edge_measurement and edge_measurement.edge_net > 0:
                reason = f"Baseline gap: started {distance_pct:.2%} above baseline"
                return "YES", edge_measurement, reason
        else:  # Price below baseline
            edge_measurement = self.edge_detector.edge_no
            if edge_measurement and edge_measurement.edge_net > 0:
                reason = f"Baseline gap: started {distance_pct:.2%} below baseline"
                return "NO", edge_measurement, reason
        
        return None
    
    def generate_signal(
        self,
        market: KalshiMarket,
        baseline: float,
        settle_timestamp: float,
        recommended_size_usd: float
    ) -> Optional[TradeSignal]:
        """Generate trade signal.
        
        Args:
            market: Market data
            baseline: Baseline price
            settle_timestamp: Settlement timestamp
            recommended_size_usd: Recommended position size from risk manager
            
        Returns:
            Trade signal or None
        """
        # Check no-trade conditions
        no_trade_reason = self.check_no_trade_conditions(market, settle_timestamp)
        if no_trade_reason:
            self.logger.debug(f"No trade: {no_trade_reason}")
            return None
        
        # Try each signal type in order of priority
        signals = []
        
        # 1. Delay capture (highest priority)
        delay_signal = self.detect_delay_capture(market)
        if delay_signal:
            side, edge_measurement, reason = delay_signal
            signals.append(("delay_capture", side, edge_measurement, reason, self.delay_weight))
        
        # 2. Momentum confirmation
        momentum_signal = self.detect_momentum(market, baseline)
        if momentum_signal:
            side, edge_measurement, reason = momentum_signal
            signals.append(("momentum", side, edge_measurement, reason, self.momentum_weight))
        
        # 3. Baseline gap
        gap_signal = self.detect_baseline_gap(market, baseline, settle_timestamp)
        if gap_signal:
            side, edge_measurement, reason = gap_signal
            signals.append(("baseline_gap", side, edge_measurement, reason, self.baseline_gap_weight))
        
        if not signals:
            return None
        
        # Select signal with highest weighted edge
        best_signal = max(signals, key=lambda s: s[2].edge_net * s[4])
        signal_type, side, edge_measurement, reason, weight = best_signal
        
        # Get confidence
        confidence = self.probability_model.get_confidence() or 0.0
        
        # Create signal
        signal = TradeSignal(
            timestamp=time.time(),
            market_id=market.ticker,
            side=side,
            signal_type=signal_type,
            p_true=edge_measurement.p_true,
            p_market=edge_measurement.p_market,
            edge=edge_measurement.edge_net,
            confidence=confidence,
            recommended_size_usd=recommended_size_usd,
            reason=reason,
            metadata={
                "baseline": baseline,
                "settle_timestamp": settle_timestamp,
                "latency_ms": edge_measurement.latency_ms,
                "edge_raw": edge_measurement.edge_raw,
                "weight": weight
            }
        )
        
        self.last_signal = signal
        
        self.logger.info(
            f"Generated signal: {signal.side} {signal.market_id}",
            signal_type=signal.signal_type,
            edge=signal.edge,
            size=signal.recommended_size_usd,
            reason=signal.reason
        )
        
        return signal
    
    def get_last_signal(self) -> Optional[TradeSignal]:
        """Get last generated signal.
        
        Returns:
            Last signal or None
        """
        return self.last_signal

