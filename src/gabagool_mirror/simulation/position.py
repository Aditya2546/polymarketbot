"""
Simulated Position Tracking.

Maintains position ledger with proper VWAP calculation.
"""

from datetime import datetime
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class SimulatedPosition:
    """
    Simulated position for a single market.
    
    Tracks both YES and NO sides with average cost basis.
    """
    market_id: str
    venue: str
    
    # YES position
    yes_qty: float = 0.0
    yes_total_cost: float = 0.0  # Total $ spent on YES
    
    # NO position
    no_qty: float = 0.0
    no_total_cost: float = 0.0  # Total $ spent on NO
    
    # PnL tracking
    realized_pnl: float = 0.0
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    settled_at: Optional[datetime] = None
    
    @property
    def yes_avg_cost(self) -> float:
        """Average cost per YES share."""
        return self.yes_total_cost / self.yes_qty if self.yes_qty > 0 else 0.0
    
    @property
    def no_avg_cost(self) -> float:
        """Average cost per NO share."""
        return self.no_total_cost / self.no_qty if self.no_qty > 0 else 0.0
    
    @property
    def total_cost(self) -> float:
        """Total cost of position."""
        return self.yes_total_cost + self.no_total_cost
    
    @property
    def is_hedged(self) -> bool:
        """Check if position has both sides."""
        return self.yes_qty > 0 and self.no_qty > 0
    
    @property
    def hedge_locked_value(self) -> float:
        """
        Value locked if both sides are held.
        
        If you have equal YES and NO, you're guaranteed $1 per pair at settlement.
        """
        hedged_qty = min(self.yes_qty, self.no_qty)
        return hedged_qty * 1.0  # $1 per pair
    
    @property
    def hedge_locked_cost(self) -> float:
        """Cost of the hedged portion."""
        hedged_qty = min(self.yes_qty, self.no_qty)
        if hedged_qty == 0:
            return 0.0
        
        # Proportional cost
        yes_portion = hedged_qty / self.yes_qty if self.yes_qty > 0 else 0
        no_portion = hedged_qty / self.no_qty if self.no_qty > 0 else 0
        
        return (self.yes_total_cost * yes_portion) + (self.no_total_cost * no_portion)
    
    @property
    def hedge_locked_edge(self) -> float:
        """
        Edge locked in the hedge.
        
        Positive = guaranteed profit at settlement.
        """
        return self.hedge_locked_value - self.hedge_locked_cost
    
    @property
    def unhedged_yes_qty(self) -> float:
        """Unhedged YES quantity."""
        return max(0, self.yes_qty - self.no_qty)
    
    @property
    def unhedged_no_qty(self) -> float:
        """Unhedged NO quantity."""
        return max(0, self.no_qty - self.yes_qty)
    
    def add_fill(self, side: str, qty: float, cost: float) -> None:
        """
        Add a fill to the position.
        
        Args:
            side: YES or NO
            qty: Quantity filled
            cost: Total cost including fees
        """
        if side == "YES":
            self.yes_qty += qty
            self.yes_total_cost += cost
        else:
            self.no_qty += qty
            self.no_total_cost += cost
        
        self.updated_at = datetime.utcnow()
    
    def reduce_position(self, side: str, qty: float) -> float:
        """
        Reduce a position (e.g., by selling).
        
        Args:
            side: YES or NO
            qty: Quantity to reduce
            
        Returns:
            Realized PnL from the reduction
        """
        if side == "YES":
            if qty > self.yes_qty:
                qty = self.yes_qty
            if qty == 0:
                return 0.0
            
            # Calculate cost basis of sold portion
            avg_cost = self.yes_avg_cost
            cost_basis = qty * avg_cost
            
            # Update position
            self.yes_qty -= qty
            self.yes_total_cost -= cost_basis
            
            # PnL will be calculated when we know the sale price
            return cost_basis
        else:
            if qty > self.no_qty:
                qty = self.no_qty
            if qty == 0:
                return 0.0
            
            avg_cost = self.no_avg_cost
            cost_basis = qty * avg_cost
            
            self.no_qty -= qty
            self.no_total_cost -= cost_basis
            
            return cost_basis
    
    def settle(self, outcome: str, payout_per_share: float = 1.0) -> float:
        """
        Settle the position at market resolution.
        
        Args:
            outcome: YES or NO
            payout_per_share: Payout per winning share (usually $1)
            
        Returns:
            Realized PnL from settlement
        """
        if outcome == "YES":
            # YES wins: YES holders get payout, NO holders get nothing
            payout = self.yes_qty * payout_per_share
            pnl = payout - self.total_cost
        else:
            # NO wins
            payout = self.no_qty * payout_per_share
            pnl = payout - self.total_cost
        
        self.realized_pnl = pnl
        self.settled_at = datetime.utcnow()
        
        return pnl
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "market_id": self.market_id,
            "venue": self.venue,
            "yes_qty": self.yes_qty,
            "yes_avg_cost": self.yes_avg_cost,
            "yes_total_cost": self.yes_total_cost,
            "no_qty": self.no_qty,
            "no_avg_cost": self.no_avg_cost,
            "no_total_cost": self.no_total_cost,
            "total_cost": self.total_cost,
            "is_hedged": self.is_hedged,
            "hedge_locked_edge": self.hedge_locked_edge,
            "realized_pnl": self.realized_pnl,
        }


class PositionLedger:
    """
    Ledger tracking all simulated positions.
    """
    
    def __init__(self, venue: str):
        """
        Initialize ledger.
        
        Args:
            venue: POLYMARKET or KALSHI
        """
        self.venue = venue
        self._positions: Dict[str, SimulatedPosition] = {}
        self._total_realized_pnl: float = 0.0
    
    def get_or_create(self, market_id: str) -> SimulatedPosition:
        """Get or create position for a market."""
        if market_id not in self._positions:
            self._positions[market_id] = SimulatedPosition(
                market_id=market_id,
                venue=self.venue
            )
        return self._positions[market_id]
    
    def add_fill(
        self,
        market_id: str,
        side: str,
        qty: float,
        cost: float
    ) -> SimulatedPosition:
        """
        Record a fill in the ledger.
        
        Args:
            market_id: Market identifier
            side: YES or NO
            qty: Quantity filled
            cost: Total cost including fees
            
        Returns:
            Updated position
        """
        position = self.get_or_create(market_id)
        position.add_fill(side, qty, cost)
        
        logger.debug(
            f"Fill recorded: {market_id} {side} {qty}@{cost/qty:.3f} "
            f"(total: {position.yes_qty}Y/{position.no_qty}N)"
        )
        
        return position
    
    def settle_market(
        self,
        market_id: str,
        outcome: str,
        payout_per_share: float = 1.0
    ) -> Tuple[float, Optional[SimulatedPosition]]:
        """
        Settle a market.
        
        Args:
            market_id: Market to settle
            outcome: YES or NO
            payout_per_share: Payout per winning share
            
        Returns:
            (realized_pnl, position)
        """
        if market_id not in self._positions:
            return 0.0, None
        
        position = self._positions[market_id]
        pnl = position.settle(outcome, payout_per_share)
        self._total_realized_pnl += pnl
        
        logger.info(
            f"Market settled: {market_id} -> {outcome} "
            f"| PnL: ${pnl:+.2f}"
        )
        
        return pnl, position
    
    @property
    def total_realized_pnl(self) -> float:
        """Total realized PnL across all settled positions."""
        return self._total_realized_pnl
    
    @property
    def total_unrealized_cost(self) -> float:
        """Total cost of unsettled positions."""
        return sum(
            p.total_cost for p in self._positions.values()
            if p.settled_at is None
        )
    
    @property
    def total_locked_edge(self) -> float:
        """Total locked edge from hedged positions."""
        return sum(
            p.hedge_locked_edge for p in self._positions.values()
            if p.is_hedged and p.settled_at is None
        )
    
    @property
    def open_positions(self) -> Dict[str, SimulatedPosition]:
        """Get all open (unsettled) positions."""
        return {
            k: v for k, v in self._positions.items()
            if v.settled_at is None and (v.yes_qty > 0 or v.no_qty > 0)
        }
    
    def get_summary(self) -> dict:
        """Get ledger summary."""
        open_pos = self.open_positions
        
        return {
            "venue": self.venue,
            "total_positions": len(self._positions),
            "open_positions": len(open_pos),
            "total_realized_pnl": self.total_realized_pnl,
            "total_unrealized_cost": self.total_unrealized_cost,
            "total_locked_edge": self.total_locked_edge,
            "total_yes_qty": sum(p.yes_qty for p in open_pos.values()),
            "total_no_qty": sum(p.no_qty for p in open_pos.values()),
        }

