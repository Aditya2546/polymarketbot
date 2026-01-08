"""Multi-channel alerting system."""

import asyncio
import aiohttp
from typing import Dict, Optional
from plyer import notification

from ..logger import StructuredLogger


class AlertManager:
    """Multi-channel alert manager."""
    
    def __init__(
        self,
        desktop_enabled: bool = True,
        desktop_sound: bool = True,
        telegram_enabled: bool = False,
        telegram_bot_token: str = "",
        telegram_chat_id: str = "",
        webhook_enabled: bool = False,
        webhook_url: str = "",
        email_enabled: bool = False,
        alert_on_signal: bool = True,
        alert_on_position: bool = True,
        alert_on_breaker: bool = True,
        alert_on_error: bool = True
    ):
        """Initialize alert manager.
        
        Args:
            desktop_enabled: Enable desktop notifications
            desktop_sound: Play sound with desktop notifications
            telegram_enabled: Enable Telegram alerts
            telegram_bot_token: Telegram bot token
            telegram_chat_id: Telegram chat ID
            webhook_enabled: Enable webhook alerts
            webhook_url: Webhook URL
            email_enabled: Enable email alerts
            alert_on_signal: Alert on new trade signal
            alert_on_position: Alert on position open/close
            alert_on_breaker: Alert on circuit breaker
            alert_on_error: Alert on errors
        """
        self.desktop_enabled = desktop_enabled
        self.desktop_sound = desktop_sound
        self.telegram_enabled = telegram_enabled
        self.telegram_bot_token = telegram_bot_token
        self.telegram_chat_id = telegram_chat_id
        self.webhook_enabled = webhook_enabled
        self.webhook_url = webhook_url
        self.email_enabled = email_enabled
        
        self.alert_on_signal = alert_on_signal
        self.alert_on_position = alert_on_position
        self.alert_on_breaker = alert_on_breaker
        self.alert_on_error = alert_on_error
        
        self.session: Optional[aiohttp.ClientSession] = None
        self.logger = StructuredLogger(__name__)
    
    async def start(self) -> None:
        """Start alert manager."""
        if self.telegram_enabled or self.webhook_enabled:
            self.session = aiohttp.ClientSession()
        
        self.logger.info(
            "Alert manager started",
            desktop=self.desktop_enabled,
            telegram=self.telegram_enabled,
            webhook=self.webhook_enabled
        )
    
    async def stop(self) -> None:
        """Stop alert manager."""
        if self.session:
            await self.session.close()
            self.session = None
    
    def _send_desktop(self, title: str, message: str) -> None:
        """Send desktop notification.
        
        Args:
            title: Notification title
            message: Notification message
        """
        if not self.desktop_enabled:
            return
        
        try:
            notification.notify(
                title=title,
                message=message,
                app_name="Kalshi BTC Assistant",
                timeout=10
            )
        except Exception as e:
            self.logger.error(f"Desktop notification failed: {e}")
    
    async def _send_telegram(self, message: str) -> None:
        """Send Telegram alert.
        
        Args:
            message: Alert message
        """
        if not self.telegram_enabled or not self.session:
            return
        
        try:
            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            payload = {
                "chat_id": self.telegram_chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
            
            async with self.session.post(url, json=payload) as response:
                if response.status != 200:
                    error = await response.text()
                    self.logger.error(f"Telegram alert failed: {error}")
        
        except Exception as e:
            self.logger.error(f"Telegram alert error: {e}")
    
    async def _send_webhook(self, data: Dict) -> None:
        """Send webhook alert.
        
        Args:
            data: Alert data
        """
        if not self.webhook_enabled or not self.session:
            return
        
        try:
            async with self.session.post(self.webhook_url, json=data) as response:
                if response.status not in [200, 201, 204]:
                    error = await response.text()
                    self.logger.error(f"Webhook alert failed: {error}")
        
        except Exception as e:
            self.logger.error(f"Webhook alert error: {e}")
    
    async def alert_signal(
        self,
        market_id: str,
        side: str,
        edge: float,
        size: float,
        reason: str
    ) -> None:
        """Alert on new trade signal.
        
        Args:
            market_id: Market identifier
            side: Trade side
            edge: Edge value
            size: Position size
            reason: Signal reason
        """
        if not self.alert_on_signal:
            return
        
        title = f"🔔 Trade Signal: {side} {market_id}"
        message = f"Side: {side}\nEdge: {edge:.2%}\nSize: ${size:.2f}\nReason: {reason}"
        
        # Desktop notification
        self._send_desktop(title, message)
        
        # Telegram
        telegram_msg = f"<b>{title}</b>\n\n{message}"
        await self._send_telegram(telegram_msg)
        
        # Webhook
        webhook_data = {
            "type": "signal",
            "market_id": market_id,
            "side": side,
            "edge": edge,
            "size": size,
            "reason": reason
        }
        await self._send_webhook(webhook_data)
    
    async def alert_position_opened(
        self,
        market_id: str,
        side: str,
        size: float,
        price: float
    ) -> None:
        """Alert on position opened.
        
        Args:
            market_id: Market identifier
            side: Trade side
            size: Position size
            price: Entry price
        """
        if not self.alert_on_position:
            return
        
        title = f"✅ Position Opened: {side} {market_id}"
        message = f"Size: ${size:.2f}\nEntry: {price:.2f}"
        
        self._send_desktop(title, message)
        
        telegram_msg = f"<b>{title}</b>\n\n{message}"
        await self._send_telegram(telegram_msg)
        
        webhook_data = {
            "type": "position_opened",
            "market_id": market_id,
            "side": side,
            "size": size,
            "price": price
        }
        await self._send_webhook(webhook_data)
    
    async def alert_position_closed(
        self,
        market_id: str,
        side: str,
        pnl: float,
        exit_price: float
    ) -> None:
        """Alert on position closed.
        
        Args:
            market_id: Market identifier
            side: Trade side
            pnl: P&L
            exit_price: Exit price
        """
        if not self.alert_on_position:
            return
        
        emoji = "🟢" if pnl >= 0 else "🔴"
        title = f"{emoji} Position Closed: {side} {market_id}"
        message = f"P&L: ${pnl:+.2f}\nExit: {exit_price:.2f}"
        
        self._send_desktop(title, message)
        
        telegram_msg = f"<b>{title}</b>\n\n{message}"
        await self._send_telegram(telegram_msg)
        
        webhook_data = {
            "type": "position_closed",
            "market_id": market_id,
            "side": side,
            "pnl": pnl,
            "exit_price": exit_price
        }
        await self._send_webhook(webhook_data)
    
    async def alert_circuit_breaker(self, reason: str) -> None:
        """Alert on circuit breaker.
        
        Args:
            reason: Breaker reason
        """
        if not self.alert_on_breaker:
            return
        
        title = "⚠️ CIRCUIT BREAKER TRIPPED"
        message = f"Reason: {reason}"
        
        self._send_desktop(title, message)
        
        telegram_msg = f"<b>{title}</b>\n\n{message}"
        await self._send_telegram(telegram_msg)
        
        webhook_data = {
            "type": "circuit_breaker",
            "reason": reason
        }
        await self._send_webhook(webhook_data)
    
    async def alert_error(self, error: str) -> None:
        """Alert on error.
        
        Args:
            error: Error message
        """
        if not self.alert_on_error:
            return
        
        title = "❌ Error"
        message = f"Error: {error}"
        
        self._send_desktop(title, message)
        
        telegram_msg = f"<b>{title}</b>\n\n{message}"
        await self._send_telegram(telegram_msg)
        
        webhook_data = {
            "type": "error",
            "error": error
        }
        await self._send_webhook(webhook_data)

