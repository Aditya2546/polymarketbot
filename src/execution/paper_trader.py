"""Paper trading implementation."""

import asyncio
import time
from typing import Optional

from ..data.kalshi_client import KalshiMarket
from ..strategy.signal_generator import TradeSignal
from ..strategy.risk_manager import RiskManager, Trade
from ..ui.alerts import AlertManager
from ..logger import StructuredLogger, TradeLogger


class PaperTrader:
    """Paper trading automation."""
    
    def __init__(
        self,
        risk_manager: RiskManager,
        alert_manager: Optional[AlertManager] = None,
        trade_logger: Optional[TradeLogger] = None,
        realistic_fills: bool = True,
        fill_delay_ms: float = 100,
        miss_rate: float = 0.05
    ):
        """Initialize paper trader.
        
        Args:
            risk_manager: Risk manager instance
            alert_manager: Alert manager instance
            trade_logger: Trade logger instance
            realistic_fills: Simulate realistic fill behavior
            fill_delay_ms: Simulated fill delay
            miss_rate: Probability of missing fill
        """
        self.risk_manager = risk_manager
        self.alert_manager = alert_manager
        self.trade_logger = trade_logger
        self.realistic_fills = realistic_fills
        self.fill_delay_ms = fill_delay_ms
        self.miss_rate = miss_rate
        
        # State
        self.is_running = False
        self.pending_signals: list = []
        
        # Logging
        self.logger = StructuredLogger(__name__)
    
    async def start(self) -> None:
        """Start paper trader."""
        self.is_running = True
        self.logger.info("Paper trader started")
    
    async def stop(self) -> None:
        """Stop paper trader."""
        self.is_running = False
        self.logger.info("Paper trader stopped")
    
    async def execute_signal(
        self,
        signal: TradeSignal,
        market: KalshiMarket
    ) -> Optional[Trade]:
        """Execute trade signal on paper.
        
        Args:
            signal: Trade signal
            market: Current market
            
        Returns:
            Trade record or None if not executed
        """
        if not self.is_running:
            return None
        
        # Check if can open position
        can_open, reason = self.risk_manager.can_open_position()
        
        if not can_open:
            self.logger.warning(
                f"Cannot execute paper trade: {reason}",
                signal=str(signal)
            )
            return None
        
        # Simulate fill delay
        if self.realistic_fills:
            await asyncio.sleep(self.fill_delay_ms / 1000)
            
            # Simulate miss rate (adverse selection)
            import random
            if random.random() < self.miss_rate:
                self.logger.info(
                    f"Paper trade missed (simulated adverse selection)",
                    signal=str(signal)
                )
                return None
        
        # Determine entry price
        entry_price = signal.p_market
        
        # Open position
        trade = self.risk_manager.open_position(
            market_id=signal.market_id,
            side=signal.side,
            size_usd=signal.recommended_size_usd,
            entry_price=entry_price
        )
        
        if trade:
            self.logger.info(
                f"Paper trade executed: {signal.side} {signal.market_id}",
                size=signal.recommended_size_usd,
                price=entry_price
            )
            
            # Log trade
            if self.trade_logger:
                self.trade_logger.log_trade(
                    trade_type="paper",
                    market_id=signal.market_id,
                    side=signal.side,
                    size=signal.recommended_size_usd,
                    price=entry_price,
                    edge=signal.edge
                )
            
            # Send alert
            if self.alert_manager:
                await self.alert_manager.alert_position_opened(
                    market_id=signal.market_id,
                    side=signal.side,
                    size=signal.recommended_size_usd,
                    price=entry_price
                )
        
        return trade
    
    async def close_position(
        self,
        trade: Trade,
        exit_price: float
    ) -> None:
        """Close paper position.
        
        Args:
            trade: Trade to close
            exit_price: Exit price
        """
        self.risk_manager.close_position(trade, exit_price)
        
        self.logger.info(
            f"Paper position closed: {trade.side} {trade.market_id}",
            pnl=trade.pnl,
            exit_price=exit_price
        )
        
        # Log trade
        if self.trade_logger:
            self.trade_logger.log_trade(
                trade_type="paper_close",
                market_id=trade.market_id,
                side=trade.side,
                size=trade.size_usd,
                price=exit_price,
                edge=0.0,
                pnl=trade.pnl
            )
        
        # Send alert
        if self.alert_manager and trade.pnl is not None:
            await self.alert_manager.alert_position_closed(
                market_id=trade.market_id,
                side=trade.side,
                pnl=trade.pnl,
                exit_price=exit_price
            )
    
    async def monitor_positions(self, market: KalshiMarket) -> None:
        """Monitor open positions and close at settlement.
        
        Args:
            market: Current market
        """
        # Check if market is settled
        if market.status != "open":
            # Market settled - close all open positions
            open_trades = list(self.risk_manager.open_trades)
            
            for trade in open_trades:
                if trade.market_id == market.ticker:
                    # Determine settlement outcome
                    # For simplicity, use last price as settlement
                    exit_price = market.last_price if market.last_price else trade.entry_price
                    
                    await self.close_position(trade, exit_price)
    
    def get_status(self) -> dict:
        """Get paper trader status.
        
        Returns:
            Status dictionary
        """
        return {
            "is_running": self.is_running,
            "realistic_fills": self.realistic_fills,
            "fill_delay_ms": self.fill_delay_ms,
            "miss_rate": self.miss_rate
        }

