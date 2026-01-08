"""Risk management for position sizing and circuit breakers."""

import time
from collections import deque
from typing import Dict, List, Optional, Deque, Tuple
from dataclasses import dataclass
import numpy as np

from ..logger import StructuredLogger


@dataclass
class Trade:
    """Trade record."""
    
    timestamp: float
    market_id: str
    side: str
    size_usd: float
    entry_price: float
    exit_price: Optional[float] = None
    exit_timestamp: Optional[float] = None
    pnl: Optional[float] = None
    
    def is_open(self) -> bool:
        """Check if trade is still open."""
        return self.exit_price is None
    
    def close(self, exit_price: float) -> None:
        """Close trade.
        
        Args:
            exit_price: Exit price
        """
        self.exit_timestamp = time.time()
        self.exit_price = exit_price
        
        # Compute PnL
        if self.side == "YES":
            self.pnl = self.size_usd * (exit_price - self.entry_price) / self.entry_price
        else:
            self.pnl = self.size_usd * (self.entry_price - exit_price) / self.entry_price


class RiskManager:
    """Risk manager for position sizing and circuit breakers."""
    
    def __init__(
        self,
        initial_bankroll_usd: float = 200.0,
        max_risk_per_trade_usd: float = 8.0,
        max_risk_per_trade_pct: float = 0.04,
        max_open_exposure_usd: float = 24.0,
        max_open_exposure_pct: float = 0.12,
        daily_loss_limit_usd: float = 20.0,
        daily_loss_limit_pct: float = 0.10,
        consecutive_loss_limit: int = 4,
        cooldown_seconds: int = 1800,
        max_drawdown_pct: float = 0.25,
        enable_edge_scaling: bool = True,
        target_edge: float = 0.05,
        min_edge_for_min_size: float = 0.02,
        min_size_fraction: float = 0.25
    ):
        """Initialize risk manager.
        
        Args:
            initial_bankroll_usd: Initial bankroll
            max_risk_per_trade_usd: Max risk per trade (USD)
            max_risk_per_trade_pct: Max risk per trade (%)
            max_open_exposure_usd: Max total open exposure (USD)
            max_open_exposure_pct: Max total open exposure (%)
            daily_loss_limit_usd: Daily loss limit (USD)
            daily_loss_limit_pct: Daily loss limit (%)
            consecutive_loss_limit: Max consecutive losses before cooldown
            cooldown_seconds: Cooldown duration after losses
            max_drawdown_pct: Max drawdown from peak
            enable_edge_scaling: Scale size with edge
            target_edge: Edge for full size
            min_edge_for_min_size: Edge for minimum size
            min_size_fraction: Minimum size fraction
        """
        self.initial_bankroll_usd = initial_bankroll_usd
        self.max_risk_per_trade_usd = max_risk_per_trade_usd
        self.max_risk_per_trade_pct = max_risk_per_trade_pct
        self.max_open_exposure_usd = max_open_exposure_usd
        self.max_open_exposure_pct = max_open_exposure_pct
        self.daily_loss_limit_usd = daily_loss_limit_usd
        self.daily_loss_limit_pct = daily_loss_limit_pct
        self.consecutive_loss_limit = consecutive_loss_limit
        self.cooldown_seconds = cooldown_seconds
        self.max_drawdown_pct = max_drawdown_pct
        self.enable_edge_scaling = enable_edge_scaling
        self.target_edge = target_edge
        self.min_edge_for_min_size = min_edge_for_min_size
        self.min_size_fraction = min_size_fraction
        
        # State
        self.current_bankroll = initial_bankroll_usd
        self.peak_bankroll = initial_bankroll_usd
        self.trades: List[Trade] = []
        self.open_trades: List[Trade] = []
        
        # Circuit breaker state
        self.is_halted = False
        self.halt_reason: Optional[str] = None
        self.halt_timestamp: Optional[float] = None
        self.cooldown_until: Optional[float] = None
        
        # Daily tracking
        self.daily_pnl = 0.0
        self.daily_start_time = time.time()
        self.consecutive_losses = 0
        
        # Logging
        self.logger = StructuredLogger(__name__)
    
    def reset_daily_tracking(self) -> None:
        """Reset daily tracking (call at start of new day)."""
        self.daily_pnl = 0.0
        self.daily_start_time = time.time()
        
        self.logger.info("Reset daily tracking")
    
    def update_bankroll(self, new_bankroll: float) -> None:
        """Update current bankroll.
        
        Args:
            new_bankroll: New bankroll value
        """
        self.current_bankroll = new_bankroll
        
        # Update peak
        if new_bankroll > self.peak_bankroll:
            self.peak_bankroll = new_bankroll
            self.logger.info(f"New peak bankroll: ${new_bankroll:.2f}")
    
    def get_open_exposure(self) -> float:
        """Get total open exposure.
        
        Returns:
            Total USD exposure in open positions
        """
        return sum(trade.size_usd for trade in self.open_trades)
    
    def get_available_risk_budget(self) -> float:
        """Get available risk budget for new trade.
        
        Returns:
            Available risk budget in USD
        """
        # Check per-trade limit
        max_per_trade = min(
            self.max_risk_per_trade_usd,
            self.current_bankroll * self.max_risk_per_trade_pct
        )
        
        # Check total exposure limit
        current_exposure = self.get_open_exposure()
        max_exposure = min(
            self.max_open_exposure_usd,
            self.current_bankroll * self.max_open_exposure_pct
        )
        
        available_exposure = max_exposure - current_exposure
        
        return min(max_per_trade, available_exposure)
    
    def compute_position_size(
        self,
        edge: float,
        confidence: float = 0.5
    ) -> float:
        """Compute recommended position size.
        
        Args:
            edge: Expected edge
            confidence: Confidence in prediction (0 to 0.5)
            
        Returns:
            Recommended size in USD
        """
        # Get available budget
        available = self.get_available_risk_budget()
        
        if available <= 0:
            return 0.0
        
        # Scale with edge if enabled
        if self.enable_edge_scaling:
            if edge < self.min_edge_for_min_size:
                size_fraction = 0.0
            elif edge >= self.target_edge:
                size_fraction = 1.0
            else:
                # Linear interpolation
                edge_range = self.target_edge - self.min_edge_for_min_size
                size_fraction = self.min_size_fraction + (1.0 - self.min_size_fraction) * (
                    (edge - self.min_edge_for_min_size) / edge_range
                )
            
            size = available * size_fraction
        else:
            size = available
        
        # Round to reasonable precision
        size = round(size, 2)
        
        return max(0.0, size)
    
    def check_circuit_breakers(self) -> Optional[str]:
        """Check if any circuit breaker should trip.
        
        Returns:
            Reason string if should halt, None otherwise
        """
        # Check if already in cooldown
        if self.cooldown_until and time.time() < self.cooldown_until:
            return f"In cooldown until {self.cooldown_until}"
        else:
            # Clear cooldown if expired
            self.cooldown_until = None
        
        # Check daily loss limit
        daily_loss_limit = min(
            self.daily_loss_limit_usd,
            self.initial_bankroll_usd * self.daily_loss_limit_pct
        )
        
        if self.daily_pnl < -daily_loss_limit:
            return f"Daily loss limit hit: ${self.daily_pnl:.2f} < ${-daily_loss_limit:.2f}"
        
        # Check max drawdown
        if self.peak_bankroll > 0:
            drawdown = (self.peak_bankroll - self.current_bankroll) / self.peak_bankroll
            
            if drawdown > self.max_drawdown_pct:
                return f"Max drawdown exceeded: {drawdown:.1%} > {self.max_drawdown_pct:.1%}"
        
        # Check consecutive losses
        if self.consecutive_losses >= self.consecutive_loss_limit:
            return f"Consecutive loss limit hit: {self.consecutive_losses} losses"
        
        return None
    
    def can_open_position(self) -> Tuple[bool, Optional[str]]:
        """Check if can open new position.
        
        Returns:
            Tuple of (can_open, reason)
        """
        # Check if halted
        if self.is_halted:
            return False, f"Trading halted: {self.halt_reason}"
        
        # Check circuit breakers
        breaker_reason = self.check_circuit_breakers()
        if breaker_reason:
            return False, breaker_reason
        
        # Check available risk budget
        available = self.get_available_risk_budget()
        if available <= 0:
            return False, "No available risk budget"
        
        return True, None
    
    def open_position(
        self,
        market_id: str,
        side: str,
        size_usd: float,
        entry_price: float
    ) -> Optional[Trade]:
        """Open new position.
        
        Args:
            market_id: Market identifier
            side: "YES" or "NO"
            size_usd: Position size in USD
            entry_price: Entry price
            
        Returns:
            Trade record or None if cannot open
        """
        can_open, reason = self.can_open_position()
        
        if not can_open:
            self.logger.warning(f"Cannot open position: {reason}")
            return None
        
        # Create trade
        trade = Trade(
            timestamp=time.time(),
            market_id=market_id,
            side=side,
            size_usd=size_usd,
            entry_price=entry_price
        )
        
        self.trades.append(trade)
        self.open_trades.append(trade)
        
        self.logger.info(
            f"Opened position: {side} {market_id}",
            size=size_usd,
            price=entry_price
        )
        
        return trade
    
    def close_position(
        self,
        trade: Trade,
        exit_price: float
    ) -> None:
        """Close position.
        
        Args:
            trade: Trade to close
            exit_price: Exit price
        """
        trade.close(exit_price)
        
        if trade in self.open_trades:
            self.open_trades.remove(trade)
        
        # Update tracking
        if trade.pnl is not None:
            self.daily_pnl += trade.pnl
            self.current_bankroll += trade.pnl
            
            # Update consecutive losses
            if trade.pnl < 0:
                self.consecutive_losses += 1
                
                # Check if should enter cooldown
                if self.consecutive_losses >= self.consecutive_loss_limit:
                    self.cooldown_until = time.time() + self.cooldown_seconds
                    self.logger.warning(
                        f"Entering cooldown for {self.cooldown_seconds}s after {self.consecutive_losses} losses"
                    )
            else:
                self.consecutive_losses = 0
            
            self.logger.info(
                f"Closed position: {trade.side} {trade.market_id}",
                pnl=trade.pnl,
                exit_price=exit_price
            )
            
            # Check circuit breakers after close
            breaker_reason = self.check_circuit_breakers()
            if breaker_reason:
                self.halt(breaker_reason)
    
    def halt(self, reason: str) -> None:
        """Halt trading.
        
        Args:
            reason: Reason for halt
        """
        self.is_halted = True
        self.halt_reason = reason
        self.halt_timestamp = time.time()
        
        self.logger.critical(
            f"TRADING HALTED: {reason}",
            reason=reason,
            timestamp=self.halt_timestamp
        )
    
    def resume(self) -> None:
        """Resume trading."""
        self.is_halted = False
        self.halt_reason = None
        self.halt_timestamp = None
        self.cooldown_until = None
        self.consecutive_losses = 0
        
        self.logger.info("Trading resumed")
    
    def get_metrics(self) -> Dict:
        """Get risk metrics.
        
        Returns:
            Metrics dictionary
        """
        closed_trades = [t for t in self.trades if not t.is_open()]
        
        if closed_trades:
            pnls = [t.pnl for t in closed_trades if t.pnl is not None]
            
            total_pnl = sum(pnls)
            win_rate = sum(1 for pnl in pnls if pnl > 0) / len(pnls) if pnls else 0
            avg_win = np.mean([pnl for pnl in pnls if pnl > 0]) if any(pnl > 0 for pnl in pnls) else 0
            avg_loss = np.mean([pnl for pnl in pnls if pnl < 0]) if any(pnl < 0 for pnl in pnls) else 0
        else:
            total_pnl = 0
            win_rate = 0
            avg_win = 0
            avg_loss = 0
        
        drawdown = (self.peak_bankroll - self.current_bankroll) / self.peak_bankroll if self.peak_bankroll > 0 else 0
        
        return {
            "current_bankroll": self.current_bankroll,
            "peak_bankroll": self.peak_bankroll,
            "total_pnl": total_pnl,
            "daily_pnl": self.daily_pnl,
            "drawdown": drawdown,
            "num_trades": len(self.trades),
            "num_open": len(self.open_trades),
            "open_exposure": self.get_open_exposure(),
            "available_budget": self.get_available_risk_budget(),
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "consecutive_losses": self.consecutive_losses,
            "is_halted": self.is_halted,
            "halt_reason": self.halt_reason,
            "in_cooldown": self.cooldown_until is not None and time.time() < self.cooldown_until
        }

