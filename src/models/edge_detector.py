"""Edge detector for identifying delay opportunities."""

import time
from collections import deque
from typing import Dict, Optional, Tuple, Deque
import numpy as np

from ..data.kalshi_client import KalshiMarket
from ..models.probability_model import ProbabilityModel
from ..logger import StructuredLogger, LatencyLogger


class EdgeMeasurement:
    """Edge measurement for a potential trade."""
    
    def __init__(
        self,
        timestamp: float,
        side: str,
        p_true: float,
        p_market: float,
        edge_raw: float,
        edge_net: float,
        latency_ms: Optional[float] = None
    ):
        """Initialize edge measurement.
        
        Args:
            timestamp: Measurement timestamp
            side: "YES" or "NO"
            p_true: True probability from model
            p_market: Market-implied probability
            edge_raw: Raw edge before costs
            edge_net: Net edge after costs
            latency_ms: Measured latency
        """
        self.timestamp = timestamp
        self.side = side
        self.p_true = p_true
        self.p_market = p_market
        self.edge_raw = edge_raw
        self.edge_net = edge_net
        self.latency_ms = latency_ms
    
    def __repr__(self) -> str:
        return (
            f"EdgeMeasurement(side={self.side}, edge_net={self.edge_net:.4f}, "
            f"p_true={self.p_true:.4f}, p_market={self.p_market:.4f})"
        )


class EdgeDetector:
    """Edge detector for identifying delay-based trading opportunities."""
    
    def __init__(
        self,
        probability_model: ProbabilityModel,
        min_edge_threshold: float = 0.03,
        fee_buffer: float = 0.007,
        slippage_buffer: float = 0.005,
        latency_buffer: float = 0.003,
        delay_window_min_seconds: int = 30,
        delay_window_max_seconds: int = 600,
        market_prob_method: str = "executable",
        min_depth_usd: float = 100.0
    ):
        """Initialize edge detector.
        
        Args:
            probability_model: Probability model instance
            min_edge_threshold: Minimum net edge to signal
            fee_buffer: Fee cost buffer
            slippage_buffer: Slippage cost buffer
            latency_buffer: Latency risk buffer
            delay_window_min_seconds: Minimum seconds before settle to trade
            delay_window_max_seconds: Maximum seconds before settle to trade
            market_prob_method: Method for computing market probability
            min_depth_usd: Minimum depth to trust market price
        """
        self.probability_model = probability_model
        self.min_edge_threshold = min_edge_threshold
        self.fee_buffer = fee_buffer
        self.slippage_buffer = slippage_buffer
        self.latency_buffer = latency_buffer
        self.delay_window_min_seconds = delay_window_min_seconds
        self.delay_window_max_seconds = delay_window_max_seconds
        self.market_prob_method = market_prob_method
        self.min_depth_usd = min_depth_usd
        
        # Latency tracking
        self.latency_measurements: Deque[float] = deque(maxlen=100)
        self.current_latency_ms: Optional[float] = None
        
        # Current edge state
        self.edge_yes: Optional[EdgeMeasurement] = None
        self.edge_no: Optional[EdgeMeasurement] = None
        self.last_update: Optional[float] = None
        
        # Timestamps for latency measurement
        self.last_underlying_update: Optional[float] = None
        self.last_market_update: Optional[float] = None
        
        # Logging
        self.logger = StructuredLogger(__name__)
        self.latency_logger: Optional[LatencyLogger] = None
    
    def set_latency_logger(self, latency_logger: LatencyLogger) -> None:
        """Set latency logger.
        
        Args:
            latency_logger: Latency logger instance
        """
        self.latency_logger = latency_logger
    
    def record_underlying_update(self) -> None:
        """Record timestamp of underlying price update."""
        self.last_underlying_update = time.time()
    
    def record_market_update(self) -> None:
        """Record timestamp of market price update and compute latency."""
        current_time = time.time()
        self.last_market_update = current_time
        
        # If we have both timestamps, compute lag
        if self.last_underlying_update is not None:
            lag_ms = (current_time - self.last_underlying_update) * 1000
            self.latency_measurements.append(lag_ms)
            self.current_latency_ms = lag_ms
            
            if self.latency_logger:
                self.latency_logger.log_latency(
                    source="market_lag",
                    latency_ms=lag_ms
                )
            
            # Warn if latency is high
            if lag_ms > 500:
                self.logger.warning(
                    f"High market latency detected: {lag_ms:.1f}ms",
                    latency_ms=lag_ms
                )
    
    def get_average_latency_ms(self) -> Optional[float]:
        """Get average latency over recent measurements.
        
        Returns:
            Average latency in ms or None
        """
        if not self.latency_measurements:
            return None
        
        return float(np.mean(self.latency_measurements))
    
    def get_latency_adjusted_threshold(self) -> float:
        """Get edge threshold adjusted for current latency.
        
        Returns:
            Adjusted threshold
        """
        avg_latency = self.get_average_latency_ms()
        
        if avg_latency is None:
            return self.min_edge_threshold
        
        # Widen threshold if latency is high
        if avg_latency > 500:
            multiplier = 1.5
        elif avg_latency > 200:
            multiplier = 1.2
        else:
            multiplier = 1.0
        
        return self.min_edge_threshold * multiplier
    
    def compute_market_probability(
        self,
        market: KalshiMarket,
        side: str
    ) -> Optional[float]:
        """Compute market-implied probability for a side.
        
        Args:
            market: Market data
            side: "YES" or "NO"
            
        Returns:
            Market probability or None
        """
        if side == "YES":
            if self.market_prob_method == "executable":
                # Use best ask to buy YES
                return market.yes_ask
            elif self.market_prob_method == "mid":
                return market.get_mid_price()
            else:
                # Weighted by depth (simplified: use mid for now)
                return market.get_mid_price()
        
        else:  # side == "NO"
            if self.market_prob_method == "executable":
                # Use best ask to buy NO
                return market.no_ask
            elif self.market_prob_method == "mid":
                mid = market.get_mid_price()
                return 1.0 - mid if mid is not None else None
            else:
                mid = market.get_mid_price()
                return 1.0 - mid if mid is not None else None
    
    def compute_edge(
        self,
        p_true: float,
        p_market: float,
        side: str
    ) -> Tuple[float, float]:
        """Compute edge for a trade.
        
        Args:
            p_true: True probability
            p_market: Market-implied probability (executable price)
            side: "YES" or "NO"
            
        Returns:
            Tuple of (edge_raw, edge_net)
        """
        # Raw edge = true probability - market price
        edge_raw = p_true - p_market
        
        # Net edge = raw edge - all costs
        total_buffer = self.fee_buffer + self.slippage_buffer + self.latency_buffer
        edge_net = edge_raw - total_buffer
        
        return edge_raw, edge_net
    
    def detect_edge(
        self,
        market: KalshiMarket,
        settle_timestamp: float
    ) -> Tuple[Optional[EdgeMeasurement], Optional[EdgeMeasurement]]:
        """Detect edge opportunities for both sides.
        
        Args:
            market: Current market data
            settle_timestamp: Settlement timestamp
            
        Returns:
            Tuple of (edge_yes, edge_no) or (None, None)
        """
        # Check if we're in valid time window
        seconds_to_settle = settle_timestamp - time.time()
        
        if seconds_to_settle < self.delay_window_min_seconds:
            # Too close to settlement
            return None, None
        
        if seconds_to_settle > self.delay_window_max_seconds:
            # Too far from settlement
            return None, None
        
        # Get true probabilities
        p_yes_true, p_no_true = self.probability_model.get_probabilities()
        
        if p_yes_true is None or p_no_true is None:
            return None, None
        
        # Get market probabilities
        p_yes_market = self.compute_market_probability(market, "YES")
        p_no_market = self.compute_market_probability(market, "NO")
        
        if p_yes_market is None or p_no_market is None:
            return None, None
        
        # Check orderbook depth/quality
        # (Simplified: just check that prices exist)
        if not market.is_tradeable():
            return None, None
        
        # Compute edges
        edge_yes_raw, edge_yes_net = self.compute_edge(p_yes_true, p_yes_market, "YES")
        edge_no_raw, edge_no_net = self.compute_edge(p_no_true, p_no_market, "NO")
        
        # Create measurements
        timestamp = time.time()
        
        edge_yes_measurement = EdgeMeasurement(
            timestamp=timestamp,
            side="YES",
            p_true=p_yes_true,
            p_market=p_yes_market,
            edge_raw=edge_yes_raw,
            edge_net=edge_yes_net,
            latency_ms=self.current_latency_ms
        )
        
        edge_no_measurement = EdgeMeasurement(
            timestamp=timestamp,
            side="NO",
            p_true=p_no_true,
            p_market=p_no_market,
            edge_raw=edge_no_raw,
            edge_net=edge_no_net,
            latency_ms=self.current_latency_ms
        )
        
        return edge_yes_measurement, edge_no_measurement
    
    def update(
        self,
        market: KalshiMarket,
        settle_timestamp: float
    ) -> None:
        """Update edge measurements.
        
        Args:
            market: Current market data
            settle_timestamp: Settlement timestamp
        """
        self.edge_yes, self.edge_no = self.detect_edge(market, settle_timestamp)
        self.last_update = time.time()
        
        if self.edge_yes is not None and self.edge_no is not None:
            self.logger.debug(
                "Updated edge measurements",
                edge_yes_net=self.edge_yes.edge_net,
                edge_no_net=self.edge_no.edge_net,
                latency_ms=self.current_latency_ms
            )
    
    def get_best_edge(self) -> Optional[EdgeMeasurement]:
        """Get best edge opportunity (highest net edge).
        
        Returns:
            Best edge measurement or None
        """
        if self.edge_yes is None and self.edge_no is None:
            return None
        
        if self.edge_yes is None:
            return self.edge_no
        
        if self.edge_no is None:
            return self.edge_yes
        
        # Return whichever has higher net edge
        if self.edge_yes.edge_net > self.edge_no.edge_net:
            return self.edge_yes
        else:
            return self.edge_no
    
    def has_signal(self) -> bool:
        """Check if we have a valid trade signal.
        
        Returns:
            True if edge exceeds threshold
        """
        best_edge = self.get_best_edge()
        
        if best_edge is None:
            return False
        
        # Get latency-adjusted threshold
        threshold = self.get_latency_adjusted_threshold()
        
        return best_edge.edge_net >= threshold
    
    def get_signal(self) -> Optional[Tuple[str, EdgeMeasurement]]:
        """Get trade signal if edge exists.
        
        Returns:
            Tuple of (side, edge_measurement) or None
        """
        if not self.has_signal():
            return None
        
        best_edge = self.get_best_edge()
        
        if best_edge is None:
            return None
        
        return best_edge.side, best_edge
    
    def get_status(self) -> Dict:
        """Get edge detector status.
        
        Returns:
            Status dictionary
        """
        best_edge = self.get_best_edge()
        
        return {
            "edge_yes": self.edge_yes.edge_net if self.edge_yes else None,
            "edge_no": self.edge_no.edge_net if self.edge_no else None,
            "best_side": best_edge.side if best_edge else None,
            "best_edge_net": best_edge.edge_net if best_edge else None,
            "has_signal": self.has_signal(),
            "current_latency_ms": self.current_latency_ms,
            "avg_latency_ms": self.get_average_latency_ms(),
            "adjusted_threshold": self.get_latency_adjusted_threshold(),
            "last_update": self.last_update
        }

