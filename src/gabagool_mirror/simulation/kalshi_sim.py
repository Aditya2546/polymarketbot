"""
Kalshi Equivalent Simulator.

Simulates execution on Kalshi using real orderbook data.
Models latency, slippage, and partial fills.
"""

import uuid
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

from .fill_model import FillModel, FillResult, FillStatus
from .position import PositionLedger, SimulatedPosition
from ..adapters.base import Orderbook
from ..adapters.kalshi_adapter import KalshiAdapter
from ..core.signal import CopySignal, SignalAction
from ..core.mapping import MarketMapping, MappingResult
from ..storage.repository import Repository
from ..config import get_settings

logger = logging.getLogger(__name__)


class KalshiSimulator:
    """
    Kalshi Simulation with realistic execution modeling.
    
    Answers: "Can I profitably copy gabagool on Kalshi given:
    - Market mapping accuracy
    - Orderbook liquidity
    - Execution latency
    - Slippage
    """
    
    def __init__(
        self,
        kalshi_adapter: Optional[KalshiAdapter] = None,
        repository: Optional[Repository] = None,
        latency_ms: int = 2000
    ):
        """
        Initialize Kalshi simulator.
        
        Args:
            kalshi_adapter: Adapter for fetching orderbooks
            repository: Database repository
            latency_ms: Simulated execution latency
        """
        self.adapter = kalshi_adapter
        self.repository = repository
        self.latency_ms = latency_ms
        
        self.mapper = MarketMapping()
        self.fill_model = FillModel()
        self.ledger = PositionLedger(venue="KALSHI")
        
        settings = get_settings()
        self.min_mapping_confidence = settings.min_mapping_confidence
        self.max_qty_scale = settings.max_qty_scale
        self.slippage_buffer_bps = settings.slippage_bps_buffer
        
        # Cache for mappings and orderbooks
        self._mapping_cache: Dict[str, MappingResult] = {}
        self._orderbook_cache: Dict[str, Tuple[Orderbook, int]] = {}  # (book, timestamp_ms)
        self._cache_ttl_ms = 5000  # 5 second cache
        
        # Metrics
        self.signals_processed = 0
        self.signals_mapped = 0
        self.signals_filled = 0
        self.signals_partial = 0
        self.signals_missed = 0
        self.total_volume = 0.0
        self.total_slippage_bps = 0.0
        
        # Per-latency metrics for experiments
        self.latency_metrics: Dict[int, Dict] = defaultdict(lambda: {
            "signals": 0,
            "fills": 0,
            "partial": 0,
            "missed": 0,
            "total_slippage": 0.0
        })
    
    async def get_mapping(
        self,
        signal: CopySignal,
        kalshi_markets: Optional[List] = None
    ) -> MappingResult:
        """
        Get or create mapping for a signal.
        """
        cache_key = signal.polymarket_market_id
        
        if cache_key in self._mapping_cache:
            return self._mapping_cache[cache_key]
        
        # Fetch Kalshi markets if not provided
        if kalshi_markets is None and self.adapter:
            # Try to get relevant markets based on signal
            kalshi_markets = []
            
            title = signal.polymarket_event_name.lower()
            if "bitcoin" in title or "btc" in title:
                kalshi_markets = await self.adapter.get_btc_15m_markets()
            elif "ethereum" in title or "eth" in title:
                kalshi_markets = await self.adapter.get_eth_15m_markets()
            else:
                # Fetch all active markets
                kalshi_markets = await self.adapter.get_markets(status="active", limit=200)
        
        # Convert to dicts if needed
        markets_data = [
            m if isinstance(m, dict) else {
                "market_id": m.market_id,
                "ticker": m.ticker,
                "title": m.title,
                "floor_strike": m.strike,
                "close_time": datetime.utcfromtimestamp(m.expiry_ts / 1000).isoformat() if m.expiry_ts else None
            }
            for m in (kalshi_markets or [])
        ]
        
        # Find mapping
        result = self.mapper.find_best_kalshi_match(
            polymarket_title=signal.polymarket_event_name,
            polymarket_market_id=signal.polymarket_market_id,
            kalshi_markets=markets_data
        )
        
        self._mapping_cache[cache_key] = result
        
        # Persist mapping
        if self.repository:
            await self.repository.save_mapping(signal.signal_id, result)
        
        return result
    
    async def get_orderbook(self, market_id: str) -> Optional[Orderbook]:
        """Get orderbook with caching."""
        now = int(datetime.utcnow().timestamp() * 1000)
        
        if market_id in self._orderbook_cache:
            book, cached_ts = self._orderbook_cache[market_id]
            if now - cached_ts < self._cache_ttl_ms:
                return book
        
        if not self.adapter:
            return None
        
        book = await self.adapter.get_orderbook(market_id)
        if book:
            self._orderbook_cache[market_id] = (book, now)
        
        return book
    
    async def process_signal(
        self,
        signal: CopySignal,
        latency_ms: Optional[int] = None
    ) -> Tuple[Optional[FillResult], Optional[SimulatedPosition]]:
        """
        Process a signal and simulate Kalshi execution.
        
        Args:
            signal: CopySignal from gabagool
            latency_ms: Override latency for experiments
            
        Returns:
            (FillResult, Position) or (None, None) if not mappable
        """
        latency = latency_ms or self.latency_ms
        self.signals_processed += 1
        
        # Get mapping
        mapping = await self.get_mapping(signal)
        
        if not mapping.is_mappable:
            logger.debug(
                f"Signal not mappable: {signal.polymarket_market_id[:20]}... "
                f"(confidence: {mapping.confidence:.2f})"
            )
            return None, None
        
        self.signals_mapped += 1
        
        # Get orderbook
        orderbook = await self.get_orderbook(mapping.kalshi_market_id)
        
        if not orderbook:
            logger.warning(f"No orderbook for {mapping.kalshi_ticker}")
            self.signals_missed += 1
            self.latency_metrics[latency]["missed"] += 1
            return None, None
        
        # Scale quantity
        scaled_qty = signal.qty * self.max_qty_scale
        
        if scaled_qty <= 0:
            return None, None
        
        # Determine limit price (signal price + buffer)
        limit_price = signal.price + (self.slippage_buffer_bps / 10000)
        limit_price = min(0.99, max(0.01, limit_price))
        
        # Simulate fill
        fill_result = self.fill_model.simulate_fill(
            orderbook=orderbook,
            side=signal.side.value,
            action=signal.action.value,
            qty=scaled_qty,
            limit_price=limit_price,
            latency_ms=latency
        )
        
        # Track metrics
        self.latency_metrics[latency]["signals"] += 1
        
        if fill_result.status == FillStatus.FILLED:
            self.signals_filled += 1
            self.latency_metrics[latency]["fills"] += 1
        elif fill_result.status == FillStatus.PARTIAL:
            self.signals_partial += 1
            self.latency_metrics[latency]["partial"] += 1
        else:
            self.signals_missed += 1
            self.latency_metrics[latency]["missed"] += 1
        
        if fill_result.filled_qty > 0:
            self.total_slippage_bps += fill_result.slippage_bps
            self.latency_metrics[latency]["total_slippage"] += fill_result.slippage_bps
            self.total_volume += fill_result.total_cost
        
        # Update position ledger
        position = None
        if fill_result.filled_qty > 0:
            if signal.action == SignalAction.BUY:
                position = self.ledger.add_fill(
                    market_id=mapping.kalshi_market_id,
                    side=signal.side.value,
                    qty=fill_result.filled_qty,
                    cost=fill_result.total_cost
                )
            else:
                position = self.ledger.get_or_create(mapping.kalshi_market_id)
                position.reduce_position(signal.side.value, fill_result.filled_qty)
        
        # Persist to database
        if self.repository:
            await self.repository.save_sim_order(
                order_id=fill_result.order_id,
                signal_id=signal.signal_id,
                venue="KALSHI",
                market_id=mapping.kalshi_market_id,
                ticker=mapping.kalshi_ticker,
                side=signal.side.value,
                action=signal.action.value,
                price=limit_price,
                qty=scaled_qty,
                latency_ms=latency,
                slippage_bps=int(fill_result.slippage_bps)
            )
            
            await self.repository.update_order_status(
                order_id=fill_result.order_id,
                status=fill_result.status.value,
                filled_qty=fill_result.filled_qty,
                filled_avg_price=fill_result.avg_fill_price
            )
            
            if fill_result.filled_qty > 0:
                for price, qty, level in fill_result.fills:
                    await self.repository.save_sim_fill(
                        order_id=fill_result.order_id,
                        price=price,
                        qty=qty,
                        fee=fill_result.total_fee / len(fill_result.fills),
                        book_level=level
                    )
                
                await self.repository.update_position(
                    venue="KALSHI",
                    market_id=mapping.kalshi_market_id,
                    side=signal.side.value,
                    qty_delta=fill_result.filled_qty if signal.action == SignalAction.BUY else -fill_result.filled_qty,
                    cost_delta=fill_result.total_cost if signal.action == SignalAction.BUY else -fill_result.total_cost,
                    avg_price=fill_result.avg_fill_price or 0
                )
        
        logger.info(
            f"[KALSHI-SIM] {fill_result.status.value.upper()} "
            f"{signal.action.value} {signal.side.value} "
            f"{fill_result.filled_qty:.2f}/{scaled_qty:.2f}@{fill_result.avg_fill_price or 0:.3f} "
            f"| Slip: {fill_result.slippage_bps:.1f}bps | Lat: {latency}ms "
            f"| {mapping.kalshi_ticker}"
        )
        
        return fill_result, position
    
    async def settle_market(
        self,
        market_id: str,
        outcome: str,
        payout_per_share: float = 1.0
    ) -> float:
        """Settle a Kalshi market."""
        pnl, position = self.ledger.settle_market(market_id, outcome, payout_per_share)
        
        if self.repository:
            await self.repository.save_outcome(
                market_id=market_id,
                venue="KALSHI",
                outcome=outcome,
                payout_per_share=payout_per_share
            )
        
        return pnl
    
    def get_metrics(self) -> dict:
        """Get simulation metrics."""
        summary = self.ledger.get_summary()
        
        fill_attempts = self.signals_filled + self.signals_partial + self.signals_missed
        fill_rate = self.signals_filled / fill_attempts if fill_attempts > 0 else 0
        avg_slippage = self.total_slippage_bps / (self.signals_filled + self.signals_partial) if (self.signals_filled + self.signals_partial) > 0 else 0
        
        return {
            "venue": "KALSHI",
            "mode": "ORDERBOOK",
            "latency_ms": self.latency_ms,
            "signals_processed": self.signals_processed,
            "signals_mapped": self.signals_mapped,
            "signals_filled": self.signals_filled,
            "signals_partial": self.signals_partial,
            "signals_missed": self.signals_missed,
            "fill_rate": fill_rate,
            "partial_rate": self.signals_partial / fill_attempts if fill_attempts > 0 else 0,
            "miss_rate": self.signals_missed / fill_attempts if fill_attempts > 0 else 0,
            "avg_slippage_bps": avg_slippage,
            "total_volume": self.total_volume,
            **summary
        }
    
    def get_latency_comparison(self) -> dict:
        """Get metrics comparison across latencies."""
        comparison = {}
        
        for latency, metrics in sorted(self.latency_metrics.items()):
            total = metrics["fills"] + metrics["partial"] + metrics["missed"]
            if total == 0:
                continue
            
            comparison[f"{latency}ms"] = {
                "signals": metrics["signals"],
                "fill_rate": metrics["fills"] / total,
                "partial_rate": metrics["partial"] / total,
                "miss_rate": metrics["missed"] / total,
                "avg_slippage_bps": metrics["total_slippage"] / (metrics["fills"] + metrics["partial"]) if (metrics["fills"] + metrics["partial"]) > 0 else 0
            }
        
        return comparison

