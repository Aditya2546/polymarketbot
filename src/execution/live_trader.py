"""Live trading implementation (disabled by default)."""

from typing import Optional

from ..data.kalshi_client import KalshiMarket, KalshiClient
from ..strategy.signal_generator import TradeSignal
from ..strategy.risk_manager import RiskManager, Trade
from ..ui.alerts import AlertManager
from ..logger import StructuredLogger, TradeLogger


class LiveTrader:
    """Live trading (disabled by default for safety)."""
    
    def __init__(
        self,
        kalshi_client: KalshiClient,
        risk_manager: RiskManager,
        alert_manager: Optional[AlertManager] = None,
        trade_logger: Optional[TradeLogger] = None,
        enabled: bool = False,
        confirmation_required: bool = True,
        confirmation_phrase: str = "I UNDERSTAND THE RISKS"
    ):
        """Initialize live trader.
        
        Args:
            kalshi_client: Kalshi client instance
            risk_manager: Risk manager instance
            alert_manager: Alert manager instance
            trade_logger: Trade logger instance
            enabled: Whether live trading is enabled
            confirmation_required: Require confirmation
            confirmation_phrase: Required confirmation phrase
        """
        self.kalshi_client = kalshi_client
        self.risk_manager = risk_manager
        self.alert_manager = alert_manager
        self.trade_logger = trade_logger
        self.enabled = enabled
        self.confirmation_required = confirmation_required
        self.confirmation_phrase = confirmation_phrase
        
        # State
        self.is_confirmed = False
        
        # Logging
        self.logger = StructuredLogger(__name__)
        
        if enabled:
            self.logger.warning(
                "⚠️  LIVE TRADING ENABLED - Real money will be used! ⚠️"
            )
    
    def confirm(self, phrase: str) -> bool:
        """Confirm live trading with safety phrase.
        
        Args:
            phrase: Confirmation phrase
            
        Returns:
            True if confirmed
        """
        if phrase == self.confirmation_phrase:
            self.is_confirmed = True
            self.logger.critical(
                "🚨 LIVE TRADING CONFIRMED - Trading with real money! 🚨"
            )
            return True
        else:
            self.logger.error("Confirmation phrase incorrect")
            return False
    
    def can_trade(self) -> tuple[bool, Optional[str]]:
        """Check if can execute live trades.
        
        Returns:
            Tuple of (can_trade, reason)
        """
        if not self.enabled:
            return False, "Live trading is disabled in config"
        
        if self.confirmation_required and not self.is_confirmed:
            return False, "Live trading not confirmed"
        
        return True, None
    
    async def execute_signal(
        self,
        signal: TradeSignal,
        market: KalshiMarket
    ) -> Optional[Trade]:
        """Execute trade signal live.
        
        SAFETY: This method executes real trades with real money.
        Only called if live trading is enabled and confirmed.
        
        Args:
            signal: Trade signal
            market: Current market
            
        Returns:
            Trade record or None
        """
        # Safety check
        can_trade, reason = self.can_trade()
        if not can_trade:
            self.logger.error(f"Cannot execute live trade: {reason}")
            return None
        
        # Risk check
        can_open, risk_reason = self.risk_manager.can_open_position()
        if not can_open:
            self.logger.warning(f"Cannot execute live trade: {risk_reason}")
            return None
        
        try:
            # PLACEHOLDER: Actual order execution would go here
            # This would involve calling Kalshi API to place order
            
            self.logger.critical(
                "🚨 LIVE TRADE EXECUTION NOT FULLY IMPLEMENTED 🚨",
                signal=str(signal)
            )
            
            # TODO: Implement actual order placement via Kalshi API
            # Example:
            # order = await self.kalshi_client.place_order(
            #     market_ticker=signal.market_id,
            #     side=signal.side,
            #     quantity=signal.recommended_size_usd,
            #     order_type="limit",
            #     price=signal.p_market
            # )
            
            return None
        
        except Exception as e:
            self.logger.error(f"Live trade execution failed: {e}", error=str(e))
            
            if self.alert_manager:
                await self.alert_manager.alert_error(f"Live trade failed: {e}")
            
            return None
    
    def get_status(self) -> dict:
        """Get live trader status.
        
        Returns:
            Status dictionary
        """
        can_trade, reason = self.can_trade()
        
        return {
            "enabled": self.enabled,
            "confirmed": self.is_confirmed,
            "can_trade": can_trade,
            "reason": reason
        }

