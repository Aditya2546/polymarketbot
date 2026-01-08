"""
Polymarket Exact Simulator.

Simulates perfect copy trading - assumes we get the same fills as gabagool.
This is the baseline "best case" scenario.
"""

import uuid
import logging
from datetime import datetime
from typing import Optional

from .position import PositionLedger, SimulatedPosition
from ..core.signal import CopySignal, SignalAction
from ..storage.repository import Repository
from ..config import get_settings

logger = logging.getLogger(__name__)


class PolymarketSimulator:
    """
    Polymarket Exact Simulation.
    
    Assumes perfect execution at gabagool's prices.
    Answers: "What's the best case if we copy perfectly?"
    """
    
    def __init__(self, repository: Optional[Repository] = None):
        """
        Initialize simulator.
        
        Args:
            repository: Database repository for persistence
        """
        self.ledger = PositionLedger(venue="POLYMARKET")
        self.repository = repository
        
        # Stats
        self.signals_processed = 0
        self.total_volume = 0.0
        
        settings = get_settings()
        self.max_qty_scale = settings.max_qty_scale
    
    async def process_signal(self, signal: CopySignal) -> Optional[SimulatedPosition]:
        """
        Process a CopySignal and simulate the fill.
        
        For Polymarket exact sim, we assume perfect fill at gabagool's price.
        
        Args:
            signal: CopySignal from gabagool
            
        Returns:
            Updated position or None
        """
        # Scale quantity based on our risk parameters
        scaled_qty = signal.qty * self.max_qty_scale
        
        if scaled_qty <= 0:
            return None
        
        # Calculate cost (perfect fill assumption)
        cost = scaled_qty * signal.price
        
        # Record in ledger
        if signal.action == SignalAction.BUY:
            position = self.ledger.add_fill(
                market_id=signal.polymarket_market_id,
                side=signal.side.value,
                qty=scaled_qty,
                cost=cost
            )
        else:
            # SELL reduces position
            position = self.ledger.get_or_create(signal.polymarket_market_id)
            position.reduce_position(signal.side.value, scaled_qty)
        
        # Persist to database
        if self.repository:
            order_id = str(uuid.uuid4())[:16]
            
            await self.repository.save_sim_order(
                order_id=order_id,
                signal_id=signal.signal_id,
                venue="POLYMARKET",
                market_id=signal.polymarket_market_id,
                side=signal.side.value,
                action=signal.action.value,
                price=signal.price,
                qty=scaled_qty
            )
            
            await self.repository.update_order_status(
                order_id=order_id,
                status="filled",
                filled_qty=scaled_qty,
                filled_avg_price=signal.price
            )
            
            await self.repository.save_sim_fill(
                order_id=order_id,
                price=signal.price,
                qty=scaled_qty,
                fee=0.0  # Polymarket has no explicit fee in this model
            )
            
            await self.repository.update_position(
                venue="POLYMARKET",
                market_id=signal.polymarket_market_id,
                side=signal.side.value,
                qty_delta=scaled_qty if signal.action == SignalAction.BUY else -scaled_qty,
                cost_delta=cost if signal.action == SignalAction.BUY else -cost,
                avg_price=signal.price
            )
        
        # Update stats
        self.signals_processed += 1
        self.total_volume += cost
        
        logger.info(
            f"[POLY-SIM] {signal.action.value} {signal.side.value} "
            f"{scaled_qty:.2f}@{signal.price:.3f} = ${cost:.2f} "
            f"| Market: {signal.polymarket_market_id[:20]}..."
        )
        
        return position
    
    async def settle_market(
        self,
        market_id: str,
        outcome: str,
        payout_per_share: float = 1.0
    ) -> float:
        """
        Settle a market and calculate realized PnL.
        
        Args:
            market_id: Market to settle
            outcome: YES or NO
            payout_per_share: Payout per winning share
            
        Returns:
            Realized PnL
        """
        pnl, position = self.ledger.settle_market(market_id, outcome, payout_per_share)
        
        # Persist outcome
        if self.repository:
            await self.repository.save_outcome(
                market_id=market_id,
                venue="POLYMARKET",
                outcome=outcome,
                payout_per_share=payout_per_share
            )
        
        return pnl
    
    def get_metrics(self) -> dict:
        """Get simulation metrics."""
        summary = self.ledger.get_summary()
        
        return {
            "venue": "POLYMARKET",
            "mode": "EXACT",
            "signals_processed": self.signals_processed,
            "total_volume": self.total_volume,
            "fill_rate": 1.0,  # Perfect fills assumed
            "avg_slippage_bps": 0,  # No slippage
            **summary
        }

