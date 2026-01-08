"""
Kalshi Adapter - Read/Write interface to Kalshi.

Provides:
- Market data (orderbooks, prices)
- Order placement (when enabled)
- Position tracking
"""

import asyncio
import aiohttp
import base64
import time
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

from .base import (
    BaseAdapter, AdapterConfig, MarketSnapshot,
    Orderbook, OrderbookLevel, Trade, Position
)
from ..config import get_settings

logger = logging.getLogger(__name__)


class KalshiAdapterConfig(AdapterConfig):
    """Kalshi-specific configuration."""
    base_url: str = "https://trading-api.kalshi.com/trade-api/v2"
    ws_url: str = "wss://trading-api.kalshi.com/trade-api/ws/v2"


class KalshiAdapter(BaseAdapter):
    """
    Adapter for Kalshi exchange.
    
    Supports:
    - Market data (always available)
    - Orderbook snapshots
    - Order placement (when enabled and authenticated)
    """
    
    def __init__(
        self,
        config: Optional[KalshiAdapterConfig] = None,
        api_key_id: Optional[str] = None,
        private_key_path: Optional[str] = None
    ):
        super().__init__(config or KalshiAdapterConfig())
        
        settings = get_settings()
        self._api_key_id = api_key_id or settings.kalshi_api_key_id
        self._private_key_path = private_key_path or settings.kalshi_private_key_path
        self._private_key = None
        
        self._session: Optional[aiohttp.ClientSession] = None
        self._authenticated = False
        
        # Cache for markets
        self._markets_cache: Dict[str, MarketSnapshot] = {}
        self._cache_ttl_ms = 60000  # 1 minute cache
        self._last_cache_update = 0
    
    @property
    def venue_name(self) -> str:
        return "KALSHI"
    
    async def connect(self) -> None:
        """Initialize connection and authenticate."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.config.timeout_ms / 1000)
            self._session = aiohttp.ClientSession(timeout=timeout)
        
        # Load private key if available
        if self._private_key_path and not self._private_key:
            try:
                key_path = Path(self._private_key_path)
                if key_path.exists():
                    with open(key_path, "rb") as f:
                        self._private_key = serialization.load_pem_private_key(
                            f.read(),
                            password=None,
                            backend=default_backend()
                        )
                    logger.info("Loaded Kalshi private key")
            except Exception as e:
                logger.warning(f"Failed to load Kalshi private key: {e}")
        
        self._connected = True
        self._authenticated = self._private_key is not None
        
        logger.info(f"Kalshi adapter connected (authenticated: {self._authenticated})")
    
    async def disconnect(self) -> None:
        """Close connection."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
        self._connected = False
        logger.info("Kalshi adapter disconnected")
    
    def _sign_request(self, method: str, path: str, timestamp: int) -> str:
        """Generate RSA signature for request."""
        if not self._private_key:
            return ""
        
        message = f"{timestamp}{method}{path}"
        signature = self._private_key.sign(
            message.encode(),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode()
    
    def _get_headers(self, method: str, path: str) -> Dict[str, str]:
        """Get request headers with authentication."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        if self._api_key_id and self._private_key:
            timestamp = int(time.time() * 1000)
            signature = self._sign_request(method, path, timestamp)
            headers.update({
                "KALSHI-ACCESS-KEY": self._api_key_id,
                "KALSHI-ACCESS-SIGNATURE": signature,
                "KALSHI-ACCESS-TIMESTAMP": str(timestamp)
            })
        
        return headers
    
    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None
    ) -> Optional[Dict]:
        """Make authenticated request to Kalshi API."""
        if not self._connected:
            await self.connect()
        
        url = f"{self.config.base_url}{path}"
        headers = self._get_headers(method, path)
        
        for attempt in range(self.config.retry_attempts):
            try:
                async with self._session.request(
                    method, url,
                    headers=headers,
                    params=params,
                    json=json_data
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    elif resp.status == 429:
                        wait_time = (attempt + 1) * 2
                        logger.warning(f"Rate limited, waiting {wait_time}s")
                        await asyncio.sleep(wait_time)
                    elif resp.status == 401:
                        logger.error("Kalshi authentication failed")
                        return None
                    else:
                        text = await resp.text()
                        logger.warning(f"Kalshi request failed: {resp.status} - {text}")
                        if resp.status >= 400 and resp.status < 500:
                            return None  # Client error, don't retry
            except asyncio.TimeoutError:
                logger.warning(f"Request timeout (attempt {attempt + 1})")
            except Exception as e:
                logger.error(f"Request error: {e}")
            
            await asyncio.sleep(self.config.retry_delay_ms / 1000)
        
        return None
    
    # === Market Data ===
    
    async def get_markets(
        self,
        series_ticker: Optional[str] = None,
        status: str = "active",
        limit: int = 100,
        **filters
    ) -> List[MarketSnapshot]:
        """Get available markets."""
        path = "/markets"
        params = {"status": status, "limit": limit}
        
        if series_ticker:
            params["series_ticker"] = series_ticker
        
        data = await self._request("GET", path, params=params)
        if not data:
            return []
        
        markets = []
        for m in data.get("markets", []):
            try:
                snapshot = self._parse_market(m)
                markets.append(snapshot)
                # Update cache
                self._markets_cache[snapshot.market_id] = snapshot
            except Exception as e:
                logger.warning(f"Failed to parse Kalshi market: {e}")
        
        self._last_cache_update = int(time.time() * 1000)
        return markets
    
    async def get_market(self, market_id: str) -> Optional[MarketSnapshot]:
        """Get a specific market by ID or ticker."""
        # Check cache first
        if market_id in self._markets_cache:
            cache_age = int(time.time() * 1000) - self._last_cache_update
            if cache_age < self._cache_ttl_ms:
                return self._markets_cache[market_id]
        
        path = f"/markets/{market_id}"
        data = await self._request("GET", path)
        
        if data and "market" in data:
            snapshot = self._parse_market(data["market"])
            self._markets_cache[market_id] = snapshot
            return snapshot
        
        return None
    
    def _parse_market(self, data: Dict) -> MarketSnapshot:
        """Parse Kalshi market to MarketSnapshot."""
        ticker = data.get("ticker", "")
        
        # Extract underlying from ticker (e.g., KXBTC15M -> BTC)
        underlying = None
        if "BTC" in ticker.upper():
            underlying = "BTC"
        elif "ETH" in ticker.upper():
            underlying = "ETH"
        
        # Parse expiry
        expiry_ts = None
        if data.get("close_time"):
            try:
                expiry_ts = int(datetime.fromisoformat(
                    data["close_time"].replace("Z", "+00:00")
                ).timestamp() * 1000)
            except:
                pass
        
        return MarketSnapshot(
            market_id=data.get("market_id", ticker),
            ticker=ticker,
            title=data.get("title", ""),
            venue="KALSHI",
            yes_bid=float(data.get("yes_bid", 0)) / 100 if data.get("yes_bid") else None,
            yes_ask=float(data.get("yes_ask", 0)) / 100 if data.get("yes_ask") else None,
            no_bid=float(data.get("no_bid", 0)) / 100 if data.get("no_bid") else None,
            no_ask=float(data.get("no_ask", 0)) / 100 if data.get("no_ask") else None,
            last_price=float(data.get("last_price", 0)) / 100 if data.get("last_price") else None,
            volume=float(data.get("volume", 0)),
            open_interest=float(data.get("open_interest", 0)),
            expiry_ts=expiry_ts,
            status=data.get("status", "active"),
            underlying=underlying,
            strike=float(data.get("floor_strike")) if data.get("floor_strike") else None
        )
    
    async def get_orderbook(self, market_id: str) -> Optional[Orderbook]:
        """Get orderbook for a market."""
        path = f"/markets/{market_id}/orderbook"
        data = await self._request("GET", path)
        
        if not data or "orderbook" not in data:
            return None
        
        book = data["orderbook"]
        
        def parse_levels(levels: List, ascending: bool = True) -> List[OrderbookLevel]:
            parsed = []
            for lvl in levels:
                parsed.append(OrderbookLevel(
                    price=float(lvl.get("price", 0)) / 100,  # Kalshi uses cents
                    qty=float(lvl.get("quantity", lvl.get("size", 0)))
                ))
            # Sort by price
            parsed.sort(key=lambda x: x.price, reverse=not ascending)
            return parsed
        
        return Orderbook(
            market_id=market_id,
            venue="KALSHI",
            timestamp=datetime.utcnow(),
            yes_bids=parse_levels(book.get("yes", {}).get("bids", []), ascending=False),
            yes_asks=parse_levels(book.get("yes", {}).get("asks", []), ascending=True),
            no_bids=parse_levels(book.get("no", {}).get("bids", []), ascending=False),
            no_asks=parse_levels(book.get("no", {}).get("asks", []), ascending=True)
        )
    
    # === 15-Minute Crypto Markets ===
    
    async def get_btc_15m_markets(self) -> List[MarketSnapshot]:
        """Get BTC 15-minute up/down markets."""
        return await self.get_markets(series_ticker="KXBTC15M", status="active")
    
    async def get_eth_15m_markets(self) -> List[MarketSnapshot]:
        """Get ETH 15-minute up/down markets."""
        return await self.get_markets(series_ticker="KXETH15M", status="active")
    
    async def find_matching_market(
        self,
        underlying: str,
        expiry_ts: int,
        tolerance_ms: int = 15 * 60 * 1000  # 15 minutes
    ) -> Optional[MarketSnapshot]:
        """
        Find a Kalshi market matching criteria.
        
        Args:
            underlying: BTC, ETH, etc
            expiry_ts: Target expiry timestamp in ms
            tolerance_ms: Acceptable time difference
            
        Returns:
            Best matching market or None
        """
        series = f"KX{underlying.upper()}15M"
        markets = await self.get_markets(series_ticker=series, status="active")
        
        best_match = None
        best_diff = float("inf")
        
        for m in markets:
            if m.expiry_ts:
                diff = abs(m.expiry_ts - expiry_ts)
                if diff < best_diff and diff <= tolerance_ms:
                    best_diff = diff
                    best_match = m
        
        return best_match
    
    # === Trade History ===
    
    async def get_trades(
        self,
        market_id: Optional[str] = None,
        wallet: Optional[str] = None,
        since_ts: Optional[int] = None,
        limit: int = 100
    ) -> List[Trade]:
        """Get trade history (fills)."""
        if not self._authenticated:
            logger.warning("Cannot get trades: not authenticated")
            return []
        
        path = "/portfolio/fills"
        params = {"limit": limit}
        
        if market_id:
            params["ticker"] = market_id
        
        data = await self._request("GET", path, params=params)
        if not data:
            return []
        
        trades = []
        for fill in data.get("fills", []):
            try:
                ts = datetime.fromisoformat(fill.get("created_time", "").replace("Z", "+00:00"))
                
                trades.append(Trade(
                    trade_id=fill.get("trade_id", ""),
                    market_id=fill.get("ticker", ""),
                    venue="KALSHI",
                    timestamp=ts,
                    side="YES" if fill.get("side") == "yes" else "NO",
                    action="BUY" if fill.get("action") == "buy" else "SELL",
                    qty=float(fill.get("count", 0)),
                    price=float(fill.get("price", 0)) / 100
                ))
            except Exception as e:
                logger.warning(f"Failed to parse Kalshi fill: {e}")
        
        return trades
    
    # === Positions ===
    
    async def get_positions(self, wallet: Optional[str] = None) -> List[Position]:
        """Get current positions."""
        if not self._authenticated:
            logger.warning("Cannot get positions: not authenticated")
            return []
        
        path = "/portfolio/positions"
        data = await self._request("GET", path)
        
        if not data:
            return []
        
        positions = []
        for pos in data.get("market_positions", []):
            try:
                positions.append(Position(
                    market_id=pos.get("ticker", ""),
                    venue="KALSHI",
                    yes_qty=float(pos.get("position", 0)) if pos.get("position", 0) > 0 else 0,
                    no_qty=abs(float(pos.get("position", 0))) if pos.get("position", 0) < 0 else 0
                ))
            except Exception as e:
                logger.warning(f"Failed to parse Kalshi position: {e}")
        
        return positions
    
    # === Order Placement (guarded) ===
    
    async def place_order(
        self,
        ticker: str,
        side: str,
        action: str,
        count: int,
        price_cents: int,
        order_type: str = "limit"
    ) -> Optional[Dict]:
        """
        Place an order on Kalshi.
        
        GUARDED: Only works if kalshi_live_enabled is True.
        
        Args:
            ticker: Market ticker
            side: "yes" or "no"
            action: "buy" or "sell"
            count: Number of contracts
            price_cents: Price in cents (1-99)
            order_type: "limit" or "market"
            
        Returns:
            Order response or None
        """
        settings = get_settings()
        
        if not settings.kalshi_live_enabled:
            logger.error("LIVE TRADING DISABLED - Set KALSHI_LIVE_ENABLED=true to enable")
            return None
        
        if not self._authenticated:
            logger.error("Cannot place order: not authenticated")
            return None
        
        path = "/portfolio/orders"
        payload = {
            "ticker": ticker,
            "side": side.lower(),
            "action": action.lower(),
            "count": count,
            "type": order_type
        }
        
        if order_type == "limit":
            payload["yes_price"] = price_cents if side.lower() == "yes" else None
            payload["no_price"] = price_cents if side.lower() == "no" else None
        
        logger.info(f"PLACING ORDER: {payload}")
        
        result = await self._request("POST", path, json_data=payload)
        
        if result:
            logger.info(f"Order placed: {result}")
        else:
            logger.error("Order placement failed")
        
        return result
    
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        settings = get_settings()
        
        if not settings.kalshi_live_enabled:
            logger.error("LIVE TRADING DISABLED")
            return False
        
        if not self._authenticated:
            logger.error("Cannot cancel order: not authenticated")
            return False
        
        path = f"/portfolio/orders/{order_id}"
        result = await self._request("DELETE", path)
        
        return result is not None
    
    async def get_open_orders(self, ticker: Optional[str] = None) -> List[Dict]:
        """Get open orders."""
        if not self._authenticated:
            return []
        
        path = "/portfolio/orders"
        params = {"status": "resting"}
        if ticker:
            params["ticker"] = ticker
        
        data = await self._request("GET", path, params=params)
        return data.get("orders", []) if data else []

