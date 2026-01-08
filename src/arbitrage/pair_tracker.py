"""
🧮 PAIR COST TRACKER
The core math behind Gabagool's strategy:
- Track average price paid for YES and NO shares
- Calculate pair cost = avg_yes + avg_no
- If pair_cost < $1.00 → GUARANTEED PROFIT

Example:
  Bought 100 YES @ $0.52 avg = $52 spent
  Bought 100 NO @ $0.45 avg = $45 spent
  Total spent: $97
  Pair cost: $0.52 + $0.45 = $0.97
  
  At settlement, one side pays $1.00 per share
  Guaranteed payout: min(100, 100) * $1.00 = $100
  Guaranteed profit: $100 - $97 = $3 (3.1% return, RISK FREE)
"""
from dataclasses import dataclass, field
from typing import Optional, List, Tuple
from datetime import datetime
import time


@dataclass
class Trade:
    """Single trade record"""
    side: str  # "YES" or "NO"
    qty: float
    price: float
    cost: float  # qty * price + fees
    timestamp: float
    fees: float = 0.0


@dataclass
class PairPosition:
    """
    Tracks YES/NO position pair for a single market
    This is the core of Gabagool's strategy
    """
    market_id: str
    market_title: str
    market_slug: str
    
    # YES position
    yes_qty: float = 0.0
    yes_total_cost: float = 0.0
    yes_trades: List[Trade] = field(default_factory=list)
    
    # NO position  
    no_qty: float = 0.0
    no_total_cost: float = 0.0
    no_trades: List[Trade] = field(default_factory=list)
    
    # Status
    profit_locked: bool = False
    locked_profit: float = 0.0
    created_at: float = field(default_factory=time.time)
    
    @property
    def avg_yes_price(self) -> float:
        """Average price paid per YES share"""
        return self.yes_total_cost / self.yes_qty if self.yes_qty > 0 else 0.0
    
    @property
    def avg_no_price(self) -> float:
        """Average price paid per NO share"""
        return self.no_total_cost / self.no_qty if self.no_qty > 0 else 0.0
    
    @property
    def pair_cost(self) -> float:
        """
        THE KEY METRIC: avg_yes + avg_no
        If < $1.00 → profit is GUARANTEED
        """
        if self.yes_qty == 0 or self.no_qty == 0:
            return float('inf')  # Can't calculate without both sides
        return self.avg_yes_price + self.avg_no_price
    
    @property
    def total_spent(self) -> float:
        """Total capital deployed"""
        return self.yes_total_cost + self.no_total_cost
    
    @property
    def hedged_qty(self) -> float:
        """
        Number of shares that are fully hedged (paired)
        This determines guaranteed payout
        """
        return min(self.yes_qty, self.no_qty)
    
    @property
    def unhedged_qty(self) -> Tuple[str, float]:
        """Returns which side is over-exposed and by how much"""
        diff = self.yes_qty - self.no_qty
        if diff > 0:
            return ("YES", diff)
        elif diff < 0:
            return ("NO", -diff)
        return ("BALANCED", 0)
    
    @property
    def guaranteed_payout(self) -> float:
        """
        At settlement, one side pays $1 per share
        Guaranteed payout = min(yes_qty, no_qty) * $1.00
        """
        return self.hedged_qty * 1.0
    
    @property
    def guaranteed_profit(self) -> float:
        """
        Profit that is mathematically locked in
        = guaranteed_payout - cost_of_hedged_shares
        """
        if self.hedged_qty == 0:
            return 0.0
        
        # Cost of the hedged portion
        hedged_cost = self.hedged_qty * self.pair_cost
        return self.hedged_qty * 1.0 - hedged_cost
    
    @property
    def profit_pct(self) -> float:
        """Return on hedged capital"""
        if self.hedged_qty == 0:
            return 0.0
        hedged_cost = self.hedged_qty * self.pair_cost
        return (self.guaranteed_profit / hedged_cost) * 100 if hedged_cost > 0 else 0
    
    def add_yes(self, qty: float, price: float, fees: float = 0.0) -> bool:
        """
        Add YES shares to position
        Returns True if trade improves or maintains profit lock
        """
        cost = qty * price + fees
        
        # Calculate new pair cost if we make this trade
        new_yes_qty = self.yes_qty + qty
        new_yes_cost = self.yes_total_cost + cost
        new_avg_yes = new_yes_cost / new_yes_qty
        
        # Only add if it doesn't break the lock (or we're not locked yet)
        if self.no_qty > 0:
            new_pair_cost = new_avg_yes + self.avg_no_price
            if new_pair_cost >= 1.0 and self.pair_cost < 1.0:
                return False  # Would break our lock!
        
        self.yes_qty = new_yes_qty
        self.yes_total_cost = new_yes_cost
        self.yes_trades.append(Trade(
            side="YES", qty=qty, price=price, 
            cost=cost, timestamp=time.time(), fees=fees
        ))
        
        self._check_lock()
        return True
    
    def add_no(self, qty: float, price: float, fees: float = 0.0) -> bool:
        """Add NO shares to position"""
        cost = qty * price + fees
        
        new_no_qty = self.no_qty + qty
        new_no_cost = self.no_total_cost + cost
        new_avg_no = new_no_cost / new_no_qty
        
        if self.yes_qty > 0:
            new_pair_cost = self.avg_yes_price + new_avg_no
            if new_pair_cost >= 1.0 and self.pair_cost < 1.0:
                return False
        
        self.no_qty = new_no_qty
        self.no_total_cost = new_no_cost
        self.no_trades.append(Trade(
            side="NO", qty=qty, price=price,
            cost=cost, timestamp=time.time(), fees=fees
        ))
        
        self._check_lock()
        return True
    
    def _check_lock(self):
        """Check if profit is now locked"""
        if self.hedged_qty > 0 and self.pair_cost < 1.0:
            self.profit_locked = True
            self.locked_profit = self.guaranteed_profit
    
    def would_improve(self, side: str, price: float) -> bool:
        """
        Check if buying at this price would improve our position
        """
        if side == "YES":
            if self.yes_qty == 0:
                return True  # First buy
            # Would this lower our average?
            return price < self.avg_yes_price
        else:
            if self.no_qty == 0:
                return True
            return price < self.avg_no_price
    
    def simulate_pair_cost(self, side: str, qty: float, price: float) -> float:
        """
        Calculate what pair cost WOULD BE if we made this trade
        Used for decision making
        """
        if side == "YES":
            new_yes_qty = self.yes_qty + qty
            new_yes_cost = self.yes_total_cost + qty * price
            new_avg_yes = new_yes_cost / new_yes_qty
            if self.no_qty == 0:
                return float('inf')
            return new_avg_yes + self.avg_no_price
        else:
            new_no_qty = self.no_qty + qty
            new_no_cost = self.no_total_cost + qty * price
            new_avg_no = new_no_cost / new_no_qty
            if self.yes_qty == 0:
                return float('inf')
            return self.avg_yes_price + new_avg_no
    
    def get_summary(self) -> dict:
        """Get position summary"""
        unhedged_side, unhedged_qty = self.unhedged_qty
        return {
            "market": self.market_title[:40],
            "yes_qty": round(self.yes_qty, 2),
            "yes_avg": round(self.avg_yes_price, 4),
            "no_qty": round(self.no_qty, 2),
            "no_avg": round(self.avg_no_price, 4),
            "pair_cost": round(self.pair_cost, 4) if self.pair_cost < 10 else "N/A",
            "hedged_qty": round(self.hedged_qty, 2),
            "unhedged": f"{unhedged_side}: {unhedged_qty:.1f}",
            "total_spent": round(self.total_spent, 2),
            "locked_profit": round(self.guaranteed_profit, 2),
            "profit_pct": f"{self.profit_pct:.2f}%",
            "status": "🔒 LOCKED" if self.profit_locked else "⏳ Building"
        }


class PairTracker:
    """
    Manages multiple pair positions across markets
    """
    
    def __init__(self, target_pair_cost: float = 0.98):
        """
        target_pair_cost: Maximum pair cost to allow (default 0.98 = 2% margin)
        """
        self.positions: dict[str, PairPosition] = {}
        self.target_pair_cost = target_pair_cost
        self.total_locked_profit = 0.0
        self.completed_positions: List[PairPosition] = []
    
    def get_or_create(self, market_id: str, title: str = "", slug: str = "") -> PairPosition:
        """Get existing position or create new one"""
        if market_id not in self.positions:
            self.positions[market_id] = PairPosition(
                market_id=market_id,
                market_title=title,
                market_slug=slug
            )
        return self.positions[market_id]
    
    def should_buy(self, market_id: str, side: str, price: float, 
                   current_qty: float = 0) -> Tuple[bool, str]:
        """
        Determine if we should buy this side at this price
        Returns (should_buy, reason)
        """
        pos = self.positions.get(market_id)
        
        if pos is None:
            # New market - buy if price is attractive
            if price < 0.50:
                return True, f"New position, good price ${price:.3f}"
            return False, f"Price ${price:.3f} not attractive for new position"
        
        # Check if profit already locked
        if pos.profit_locked:
            return False, "Profit already locked"
        
        # Check if this would break an existing lock
        if pos.hedged_qty > 0:
            simulated = pos.simulate_pair_cost(side, 1.0, price)
            if simulated >= 1.0 and pos.pair_cost < 1.0:
                return False, f"Would break lock: pair cost {pos.pair_cost:.3f} → {simulated:.3f}"
        
        # Check if price improves our average
        if not pos.would_improve(side, price):
            if side == "YES":
                return False, f"Price ${price:.3f} > avg ${pos.avg_yes_price:.3f}"
            else:
                return False, f"Price ${price:.3f} > avg ${pos.avg_no_price:.3f}"
        
        # Check balance - don't over-accumulate one side
        if side == "YES" and pos.yes_qty > pos.no_qty * 2 + 10:
            return False, f"Over-exposed to YES ({pos.yes_qty:.0f} vs {pos.no_qty:.0f})"
        if side == "NO" and pos.no_qty > pos.yes_qty * 2 + 10:
            return False, f"Over-exposed to NO ({pos.no_qty:.0f} vs {pos.yes_qty:.0f})"
        
        # Check if pair cost would exceed target
        simulated = pos.simulate_pair_cost(side, 1.0, price)
        if simulated > self.target_pair_cost and simulated < float('inf'):
            return False, f"Would exceed target: ${simulated:.3f} > ${self.target_pair_cost}"
        
        return True, f"Good buy at ${price:.3f}"
    
    def record_trade(self, market_id: str, side: str, qty: float, 
                     price: float, fees: float = 0.0,
                     title: str = "", slug: str = "") -> bool:
        """Record a completed trade"""
        pos = self.get_or_create(market_id, title, slug)
        
        if side.upper() == "YES":
            return pos.add_yes(qty, price, fees)
        else:
            return pos.add_no(qty, price, fees)
    
    def settle_market(self, market_id: str, winning_side: str) -> Optional[float]:
        """
        Settle a market and calculate actual P&L
        Returns profit/loss amount
        """
        if market_id not in self.positions:
            return None
        
        pos = self.positions[market_id]
        
        if winning_side.upper() == "YES":
            # YES pays $1 per share, NO pays $0
            payout = pos.yes_qty * 1.0
        else:
            # NO pays $1 per share, YES pays $0
            payout = pos.no_qty * 1.0
        
        profit = payout - pos.total_spent
        
        # Move to completed
        self.completed_positions.append(pos)
        del self.positions[market_id]
        
        return profit
    
    def get_all_summaries(self) -> List[dict]:
        """Get summaries for all active positions"""
        return [pos.get_summary() for pos in self.positions.values()]
    
    def get_total_stats(self) -> dict:
        """Get aggregate statistics"""
        total_spent = sum(p.total_spent for p in self.positions.values())
        total_locked = sum(p.guaranteed_profit for p in self.positions.values() if p.profit_locked)
        locked_count = sum(1 for p in self.positions.values() if p.profit_locked)
        
        return {
            "active_positions": len(self.positions),
            "locked_positions": locked_count,
            "total_deployed": round(total_spent, 2),
            "total_locked_profit": round(total_locked, 2),
            "completed_positions": len(self.completed_positions),
            "realized_profit": round(sum(
                p.guaranteed_profit for p in self.completed_positions
            ), 2)
        }

