"""
Risk Management Module
Position sizing, limits, and portfolio management
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime, date
import time

from .config import CONFIG

@dataclass
class Position:
    """Open position"""
    market_id: str
    title: str
    side: str
    outcome: str
    slug: str
    
    # Execution details
    qty: float
    entry_price: float
    entry_time: float
    
    # Costs paid
    fees_paid: float
    slippage_pct: float
    
    # For P&L calc
    venue: str
    gabagool_price: float
    
    # Status
    status: str = "open"  # open, closed, settled
    exit_price: Optional[float] = None
    exit_time: Optional[float] = None
    pnl: Optional[float] = None
    
    @property
    def age_seconds(self) -> float:
        return time.time() - self.entry_time
    
    @property
    def cost_basis(self) -> float:
        """Total cost to enter position"""
        return self.qty * self.entry_price + self.fees_paid
    
    @property
    def current_value(self) -> float:
        """Current value (at entry price for open positions)"""
        return self.qty * (self.exit_price or self.entry_price)

@dataclass
class Wallet:
    """Portfolio for a venue"""
    venue: str
    starting_balance: float
    balance: float
    
    positions: Dict[str, Position] = field(default_factory=dict)
    closed_positions: List[Position] = field(default_factory=list)
    
    # Stats
    wins: int = 0
    losses: int = 0
    total_fees_paid: float = 0.0
    total_slippage_cost: float = 0.0
    total_trades: int = 0
    rejected_trades: int = 0
    
    # Daily tracking
    daily_pnl: float = 0.0
    daily_high_water: float = 0.0
    last_reset_date: Optional[date] = None
    
    @property
    def open_position_value(self) -> float:
        """Total value locked in positions"""
        return sum(p.qty * p.entry_price for p in self.positions.values())
    
    @property
    def available_balance(self) -> float:
        """Balance available for new trades (with reserve)"""
        reserve = self.balance * CONFIG.risk.BALANCE_RESERVE_PCT
        return max(0, self.balance - reserve)
    
    @property
    def total_pnl(self) -> float:
        """Total P&L from starting balance"""
        return self.balance - self.starting_balance
    
    @property
    def total_pnl_pct(self) -> float:
        """P&L as percentage"""
        return (self.total_pnl / self.starting_balance) * 100 if self.starting_balance > 0 else 0
    
    @property
    def win_rate(self) -> float:
        """Win rate percentage"""
        total = self.wins + self.losses
        return (self.wins / total * 100) if total > 0 else 0
    
    def reset_daily_tracking(self):
        """Reset daily stats at start of new day"""
        today = date.today()
        if self.last_reset_date != today:
            self.daily_pnl = 0.0
            self.daily_high_water = self.balance
            self.last_reset_date = today


class RiskManager:
    """
    Manages position sizing, limits, and risk controls
    """
    
    def __init__(self):
        self.circuit_breaker_triggered = False
        self.circuit_breaker_reason = ""
    
    def calculate_position_size(
        self,
        wallet: Wallet,
        price: float,
        gabagool_size: float,
        gabagool_price: float
    ) -> float:
        """
        Calculate appropriate position size based on:
        1. Our capital vs gabagool's (proportional scaling)
        2. Available balance
        3. Max position limits
        4. Number of open positions
        """
        # Reset daily tracking
        wallet.reset_daily_tracking()
        
        # Check circuit breaker
        if self.circuit_breaker_triggered:
            return 0.0
        
        # Check position limit
        if len(wallet.positions) >= CONFIG.risk.MAX_OPEN_POSITIONS:
            return 0.0
        
        # Check daily drawdown
        if wallet.daily_pnl < -(wallet.starting_balance * CONFIG.risk.MAX_DAILY_DRAWDOWN_PCT):
            self.circuit_breaker_triggered = True
            self.circuit_breaker_reason = f"Daily drawdown limit hit: ${wallet.daily_pnl:.2f}"
            return 0.0
        
        available = wallet.available_balance
        if available < CONFIG.risk.MIN_POSITION_USD:
            return 0.0
        
        # Calculate gabagool's trade value
        gabagool_trade_value = gabagool_size * gabagool_price
        
        # Estimate gabagool's total capital (~$500k-2M based on his activity)
        estimated_gabagool_capital = 1_000_000  # $1M estimate
        
        # Scale proportionally to our capital
        our_capital = wallet.starting_balance
        scale_factor = our_capital / estimated_gabagool_capital
        
        # Our target trade value
        target_value = gabagool_trade_value * scale_factor
        
        # Apply limits
        target_value = max(CONFIG.risk.MIN_POSITION_USD, target_value)
        target_value = min(CONFIG.risk.MAX_POSITION_USD, target_value)
        target_value = min(available * CONFIG.risk.MAX_POSITION_PCT / 0.15, target_value)  # Normalize
        target_value = min(available, target_value)
        
        # Reduce size as we get more positions (diversification)
        position_count = len(wallet.positions)
        if position_count > 10:
            target_value *= 0.7
        if position_count > 20:
            target_value *= 0.7
        
        # Convert to shares
        if price > 0:
            shares = target_value / price
        else:
            shares = 0
        
        return shares
    
    def should_skip_trade(
        self,
        slippage_pct: float,
        available_liquidity: float,
        target_size_usd: float
    ) -> tuple[bool, str]:
        """
        Determine if we should skip this trade
        
        Returns:
            (should_skip, reason)
        """
        # Slippage check
        if slippage_pct > CONFIG.risk.MAX_SLIPPAGE_PCT:
            return True, f"Slippage {slippage_pct*100:.1f}% > {CONFIG.risk.MAX_SLIPPAGE_PCT*100:.0f}%"
        
        # Liquidity check
        if available_liquidity < target_size_usd * 0.5:
            return True, f"Low liquidity: ${available_liquidity:.0f} < ${target_size_usd*0.5:.0f}"
        
        return False, ""
    
    def update_daily_pnl(self, wallet: Wallet, pnl: float):
        """Update daily P&L tracking"""
        wallet.daily_pnl += pnl
        wallet.daily_high_water = max(wallet.daily_high_water, wallet.balance)
    
    def get_risk_summary(self, wallet: Wallet) -> dict:
        """Get current risk metrics"""
        return {
            "balance": wallet.balance,
            "available": wallet.available_balance,
            "open_positions": len(wallet.positions),
            "open_value": wallet.open_position_value,
            "daily_pnl": wallet.daily_pnl,
            "total_pnl": wallet.total_pnl,
            "win_rate": wallet.win_rate,
            "circuit_breaker": self.circuit_breaker_triggered,
            "fees_paid": wallet.total_fees_paid,
            "slippage_cost": wallet.total_slippage_cost
        }

