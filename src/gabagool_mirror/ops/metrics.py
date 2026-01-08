"""
Prometheus Metrics.

Exposes metrics for monitoring the copy trading system.
"""

import asyncio
from datetime import datetime
from typing import Dict, Optional
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)

# Try to import prometheus_client, but make it optional
try:
    from prometheus_client import Counter, Gauge, Histogram, REGISTRY, generate_latest
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logger.warning("prometheus_client not installed - metrics disabled")


class MetricsCollector:
    """
    Collects and exposes metrics for the copy trading system.
    
    If prometheus_client is not available, metrics are stored in memory.
    """
    
    def __init__(self, prefix: str = "gabagool_mirror"):
        """
        Initialize metrics collector.
        
        Args:
            prefix: Metrics name prefix
        """
        self.prefix = prefix
        self._memory_metrics: Dict[str, float] = defaultdict(float)
        self._memory_histograms: Dict[str, list] = defaultdict(list)
        
        if PROMETHEUS_AVAILABLE:
            self._setup_prometheus_metrics()
        else:
            self._counters = {}
            self._gauges = {}
            self._histograms = {}
    
    def _setup_prometheus_metrics(self) -> None:
        """Setup Prometheus metrics."""
        p = self.prefix
        
        # Counters
        self.signals_ingested = Counter(
            f"{p}_signals_ingested_total",
            "Total signals ingested from gabagool"
        )
        
        self.signals_mapped = Counter(
            f"{p}_signals_mapped_total",
            "Signals successfully mapped to Kalshi",
            ["venue"]
        )
        
        self.signals_filled = Counter(
            f"{p}_signals_filled_total",
            "Signals that were filled",
            ["venue", "status"]
        )
        
        self.missed_trades = Counter(
            f"{p}_missed_trades_total",
            "Total missed trades"
        )
        
        # Gauges
        self.mapping_success_rate = Gauge(
            f"{p}_mapping_success_rate",
            "Rate of successful mappings"
        )
        
        self.kalshi_fill_rate = Gauge(
            f"{p}_kalshi_fill_rate",
            "Kalshi simulation fill rate"
        )
        
        self.pnl_polymarket = Gauge(
            f"{p}_pnl_polymarket_sim",
            "Simulated PnL on Polymarket exact"
        )
        
        self.pnl_kalshi = Gauge(
            f"{p}_pnl_kalshi_sim",
            "Simulated PnL on Kalshi"
        )
        
        self.circuit_breaker_state = Gauge(
            f"{p}_circuit_breaker_state",
            "Circuit breaker state (0=off, 1=on)"
        )
        
        self.open_positions = Gauge(
            f"{p}_open_positions",
            "Number of open positions",
            ["venue"]
        )
        
        # Histograms
        self.slippage_bps = Histogram(
            f"{p}_slippage_bps",
            "Slippage in basis points",
            buckets=[0, 5, 10, 20, 50, 100, 200, 500]
        )
        
        self.latency_ms = Histogram(
            f"{p}_latency_ms",
            "Execution latency in milliseconds",
            buckets=[100, 500, 1000, 2000, 5000, 10000]
        )
    
    def inc_signals_ingested(self) -> None:
        """Increment signals ingested counter."""
        if PROMETHEUS_AVAILABLE:
            self.signals_ingested.inc()
        self._memory_metrics["signals_ingested"] += 1
    
    def inc_signals_mapped(self, venue: str) -> None:
        """Increment signals mapped counter."""
        if PROMETHEUS_AVAILABLE:
            self.signals_mapped.labels(venue=venue).inc()
        self._memory_metrics[f"signals_mapped_{venue}"] += 1
    
    def inc_signals_filled(self, venue: str, status: str) -> None:
        """Increment signals filled counter."""
        if PROMETHEUS_AVAILABLE:
            self.signals_filled.labels(venue=venue, status=status).inc()
        self._memory_metrics[f"signals_filled_{venue}_{status}"] += 1
    
    def inc_missed_trades(self) -> None:
        """Increment missed trades counter."""
        if PROMETHEUS_AVAILABLE:
            self.missed_trades.inc()
        self._memory_metrics["missed_trades"] += 1
    
    def set_mapping_success_rate(self, rate: float) -> None:
        """Set mapping success rate."""
        if PROMETHEUS_AVAILABLE:
            self.mapping_success_rate.set(rate)
        self._memory_metrics["mapping_success_rate"] = rate
    
    def set_fill_rate(self, rate: float) -> None:
        """Set Kalshi fill rate."""
        if PROMETHEUS_AVAILABLE:
            self.kalshi_fill_rate.set(rate)
        self._memory_metrics["kalshi_fill_rate"] = rate
    
    def set_pnl(self, venue: str, pnl: float) -> None:
        """Set PnL for a venue."""
        if PROMETHEUS_AVAILABLE:
            if venue == "POLYMARKET":
                self.pnl_polymarket.set(pnl)
            else:
                self.pnl_kalshi.set(pnl)
        self._memory_metrics[f"pnl_{venue.lower()}"] = pnl
    
    def set_circuit_breaker(self, active: bool) -> None:
        """Set circuit breaker state."""
        if PROMETHEUS_AVAILABLE:
            self.circuit_breaker_state.set(1 if active else 0)
        self._memory_metrics["circuit_breaker"] = 1 if active else 0
    
    def set_open_positions(self, venue: str, count: int) -> None:
        """Set open positions count."""
        if PROMETHEUS_AVAILABLE:
            self.open_positions.labels(venue=venue).set(count)
        self._memory_metrics[f"open_positions_{venue.lower()}"] = count
    
    def observe_slippage(self, bps: float) -> None:
        """Observe slippage value."""
        if PROMETHEUS_AVAILABLE:
            self.slippage_bps.observe(bps)
        self._memory_histograms["slippage_bps"].append(bps)
    
    def observe_latency(self, ms: float) -> None:
        """Observe latency value."""
        if PROMETHEUS_AVAILABLE:
            self.latency_ms.observe(ms)
        self._memory_histograms["latency_ms"].append(ms)
    
    def get_metrics_text(self) -> str:
        """Get metrics in Prometheus text format."""
        if PROMETHEUS_AVAILABLE:
            return generate_latest(REGISTRY).decode("utf-8")
        
        # Fallback: generate simple text format
        lines = []
        for name, value in sorted(self._memory_metrics.items()):
            lines.append(f"{self.prefix}_{name} {value}")
        
        return "\n".join(lines)
    
    def get_metrics_dict(self) -> dict:
        """Get all metrics as dictionary."""
        return dict(self._memory_metrics)


# Global metrics instance
_metrics: Optional[MetricsCollector] = None


def get_metrics() -> MetricsCollector:
    """Get or create the global metrics collector."""
    global _metrics
    if _metrics is None:
        _metrics = MetricsCollector()
    return _metrics

