"""
Polymarket Adapter - Read-only interface to Polymarket.

Provides:
- Wallet activity tracking (gabagool trades)
- Market data
- Trade history
"""

import asyncio
import aiohttp
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from .base import (
    BaseAdapter, AdapterConfig, MarketSnapshot, 
    Orderbook, OrderbookLevel, Trade, Position
)
from ..core.signal import CopySignal, SignalAction, SignalSide
from ..config import get_settings

logger = logging.getLogger(__name__)


class PolymarketAdapterConfig(AdapterConfig):
    """Polymarket-specific configuration."""
    gamma_api: str = "https://gamma-api.polymarket.com"
    clob_api: str = "https://clob.polymarket.com"
    data_api: str = "https://data-api.polymarket.com"


class PolymarketAdapter(BaseAdapter):
    """
    Read-only adapter for Polymarket.
    
    Used to:
    - Track gabagool22 wallet activity
    - Get market data for mapping
    - Retrieve trade history
    """
    
    def __init__(self, config: Optional[PolymarketAdapterConfig] = None):
        super().__init__(config or PolymarketAdapterConfig())
        self._session: Optional[aiohttp.ClientSession] = None
        self._last_activity_ts: int = 0
    
    @property
    def venue_name(self) -> str:
        return "POLYMARKET"
    
    async def connect(self) -> None:
        """Initialize HTTP session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.config.timeout_ms / 1000)
            self._session = aiohttp.ClientSession(timeout=timeout)
            self._connected = True
            logger.info("Polymarket adapter connected")
    
    async def disconnect(self) -> None:
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
        self._connected = False
        logger.info("Polymarket adapter disconnected")
    
    async def _request(
        self,
        url: str,
        method: str = "GET",
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None
    ) -> Optional[Dict]:
        """Make HTTP request with retry logic."""
        if not self._connected:
            await self.connect()
        
        for attempt in range(self.config.retry_attempts):
            try:
                async with self._session.request(
                    method, url, params=params, json=json_data
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    elif resp.status == 429:
                        # Rate limited - wait and retry
                        wait_time = (attempt + 1) * self.config.retry_delay_ms / 1000
                        logger.warning(f"Rate limited, waiting {wait_time}s")
                        await asyncio.sleep(wait_time)
                    else:
                        logger.warning(f"Request failed: {resp.status} - {await resp.text()}")
                        return None
            except asyncio.TimeoutError:
                logger.warning(f"Request timeout (attempt {attempt + 1})")
            except Exception as e:
                logger.error(f"Request error: {e}")
            
            await asyncio.sleep(self.config.retry_delay_ms / 1000)
        
        return None
    
    # === Market Data ===
    
    async def get_markets(self, **filters) -> List[MarketSnapshot]:
        """Get available markets."""
        url = f"{self.config.gamma_api}/markets"
        params = {
            "limit": filters.get("limit", 100),
            "active": str(filters.get("active", True)).lower()
        }
        
        data = await self._request(url, params=params)
        if not data:
            return []
        
        markets = []
        for m in data if isinstance(data, list) else data.get("markets", []):
            try:
                markets.append(self._parse_market(m))
            except Exception as e:
                logger.warning(f"Failed to parse market: {e}")
        
        return markets
    
    async def get_market(self, market_id: str) -> Optional[MarketSnapshot]:
        """Get a specific market by ID."""
        # Try condition ID first
        url = f"{self.config.gamma_api}/markets/{market_id}"
        data = await self._request(url)
        
        if data:
            return self._parse_market(data)
        
        return None
    
    def _parse_market(self, data: Dict) -> MarketSnapshot:
        """Parse Polymarket market data to MarketSnapshot."""
        # Get pricing from outcomes
        outcomes = data.get("outcomes", [])
        yes_price = None
        no_price = None
        
        for outcome in outcomes:
            if outcome.get("name", "").lower() in ("yes", "up"):
                yes_price = float(outcome.get("price", 0))
            elif outcome.get("name", "").lower() in ("no", "down"):
                no_price = float(outcome.get("price", 0))
        
        return MarketSnapshot(
            market_id=data.get("conditionId", data.get("id", "")),
            ticker=data.get("slug", ""),
            title=data.get("question", data.get("title", "")),
            venue="POLYMARKET",
            yes_bid=yes_price,
            yes_ask=yes_price,
            no_bid=no_price,
            no_ask=no_price,
            last_price=yes_price,
            volume=float(data.get("volume", 0)),
            status="active" if data.get("active", True) else "closed",
            underlying=self._detect_underlying(data.get("question", "")),
        )
    
    def _detect_underlying(self, title: str) -> Optional[str]:
        """Detect underlying asset from market title."""
        title_lower = title.lower()
        if "bitcoin" in title_lower or "btc" in title_lower:
            return "BTC"
        elif "ethereum" in title_lower or "eth" in title_lower:
            return "ETH"
        elif "solana" in title_lower or "sol" in title_lower:
            return "SOL"
        return None
    
    async def get_orderbook(self, market_id: str) -> Optional[Orderbook]:
        """Get orderbook for a market (limited on Polymarket)."""
        # Polymarket CLOB orderbook endpoint
        url = f"{self.config.clob_api}/book"
        params = {"token_id": market_id}
        
        data = await self._request(url, params=params)
        if not data:
            return None
        
        def parse_levels(levels: List) -> List[OrderbookLevel]:
            return [
                OrderbookLevel(price=float(l.get("price", 0)), qty=float(l.get("size", 0)))
                for l in levels
            ]
        
        return Orderbook(
            market_id=market_id,
            venue="POLYMARKET",
            timestamp=datetime.utcnow(),
            yes_bids=parse_levels(data.get("bids", [])),
            yes_asks=parse_levels(data.get("asks", [])),
            no_bids=[],  # Polymarket separates YES/NO tokens
            no_asks=[]
        )
    
    # === Trade History ===
    
    async def get_trades(
        self,
        market_id: Optional[str] = None,
        wallet: Optional[str] = None,
        since_ts: Optional[int] = None,
        limit: int = 100
    ) -> List[Trade]:
        """Get trade history for a wallet."""
        if not wallet:
            return []
        
        # Use gamma-api for user activity
        url = f"{self.config.gamma_api}/users/{wallet}/activity"
        params = {"limit": limit}
        
        if since_ts:
            # Convert ms to ISO timestamp
            params["after"] = datetime.utcfromtimestamp(since_ts / 1000).isoformat() + "Z"
        
        data = await self._request(url, params=params)
        if not data:
            # Try alternative endpoint
            return await self._get_trades_from_subgraph(wallet, since_ts, limit)
        
        trades = []
        activities = data if isinstance(data, list) else data.get("activities", [])
        
        for activity in activities:
            try:
                trade = self._parse_activity_to_trade(activity)
                if trade:
                    # Filter by market if specified
                    if market_id and trade.market_id != market_id:
                        continue
                    trades.append(trade)
            except Exception as e:
                logger.warning(f"Failed to parse activity: {e}")
        
        return trades
    
    async def _get_trades_from_subgraph(
        self,
        wallet: str,
        since_ts: Optional[int] = None,
        limit: int = 100
    ) -> List[Trade]:
        """Fallback: get trades from Polymarket subgraph."""
        query = """
        query UserTrades($user: String!, $first: Int!, $skip: Int!) {
            marketTrades(
                where: {user: $user}
                first: $first
                skip: $skip
                orderBy: timestamp
                orderDirection: desc
            ) {
                id
                transactionHash
                timestamp
                user
                asset
                outcome
                side
                size
                price
                feeAmount
            }
        }
        """
        
        # Polymarket subgraph URL
        subgraph_url = "https://api.thegraph.com/subgraphs/name/polymarket/matic-markets-5"
        
        try:
            async with self._session.post(
                subgraph_url,
                json={
                    "query": query,
                    "variables": {
                        "user": wallet.lower(),
                        "first": limit,
                        "skip": 0
                    }
                }
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    trades_data = result.get("data", {}).get("marketTrades", [])
                    
                    trades = []
                    for t in trades_data:
                        try:
                            ts = int(t.get("timestamp", 0))
                            if since_ts and ts < since_ts / 1000:
                                continue
                            
                            trades.append(Trade(
                                trade_id=t.get("id", ""),
                                market_id=t.get("asset", ""),
                                venue="POLYMARKET",
                                timestamp=datetime.utcfromtimestamp(ts),
                                side="YES" if t.get("outcome", "").upper() in ("YES", "UP") else "NO",
                                action=t.get("side", "BUY").upper(),
                                qty=float(t.get("size", 0)),
                                price=float(t.get("price", 0)),
                                taker=wallet,
                                tx_hash=t.get("transactionHash")
                            ))
                        except Exception as e:
                            logger.warning(f"Failed to parse subgraph trade: {e}")
                    
                    return trades
        except Exception as e:
            logger.error(f"Subgraph query failed: {e}")
        
        return []
    
    def _parse_activity_to_trade(self, activity: Dict) -> Optional[Trade]:
        """Parse activity to Trade."""
        # Handle different activity types
        action_type = activity.get("type", "").upper()
        if action_type not in ("BUY", "SELL", "TRADE"):
            return None
        
        ts = activity.get("timestamp", 0)
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except:
                ts = datetime.utcnow()
        elif isinstance(ts, (int, float)):
            if ts > 1e12:
                ts = datetime.utcfromtimestamp(ts / 1000)
            else:
                ts = datetime.utcfromtimestamp(ts)
        
        # Determine side
        outcome = activity.get("outcome", "").upper()
        if outcome in ("YES", "UP"):
            side = "YES"
        elif outcome in ("NO", "DOWN"):
            side = "NO"
        else:
            side = "YES"  # Default
        
        return Trade(
            trade_id=activity.get("id", activity.get("transactionHash", "")),
            market_id=activity.get("conditionId", activity.get("asset", "")),
            venue="POLYMARKET",
            timestamp=ts,
            side=side,
            action="SELL" if action_type == "SELL" else "BUY",
            qty=float(activity.get("size", activity.get("shares", 0))),
            price=float(activity.get("price", 0)),
            taker=activity.get("user", activity.get("proxyWallet", "")),
            tx_hash=activity.get("transactionHash")
        )
    
    # === Positions ===
    
    async def get_positions(self, wallet: Optional[str] = None) -> List[Position]:
        """Get positions for a wallet."""
        if not wallet:
            return []
        
        url = f"{self.config.gamma_api}/users/{wallet}/positions"
        data = await self._request(url)
        
        if not data:
            return []
        
        positions = []
        for p in data if isinstance(data, list) else data.get("positions", []):
            try:
                outcome = p.get("outcome", "").upper()
                is_yes = outcome in ("YES", "UP")
                
                pos = Position(
                    market_id=p.get("conditionId", p.get("asset", "")),
                    venue="POLYMARKET",
                    yes_qty=float(p.get("shares", 0)) if is_yes else 0,
                    no_qty=float(p.get("shares", 0)) if not is_yes else 0,
                    yes_avg_cost=float(p.get("avgPrice", 0)) if is_yes else 0,
                    no_avg_cost=float(p.get("avgPrice", 0)) if not is_yes else 0
                )
                positions.append(pos)
            except Exception as e:
                logger.warning(f"Failed to parse position: {e}")
        
        return positions
    
    # === Gabagool-specific Methods ===
    
    async def get_gabagool_trades(
        self,
        since_ts: Optional[int] = None,
        limit: int = 100
    ) -> List[CopySignal]:
        """
        Get gabagool22's recent trades as CopySignals.
        
        This is the primary method for the copytrader.
        """
        settings = get_settings()
        wallet = settings.gabagool_wallet
        
        trades = await self.get_trades(
            wallet=wallet,
            since_ts=since_ts,
            limit=limit
        )
        
        signals = []
        for i, trade in enumerate(trades):
            try:
                signal = CopySignal(
                    signal_id=CopySignal.generate_signal_id(
                        polymarket_trade_id=trade.trade_id,
                        fill_index=i,
                        tx_hash=trade.tx_hash
                    ),
                    ts_ms=int(trade.timestamp.timestamp() * 1000),
                    source="gabagool22",
                    polymarket_market_id=trade.market_id,
                    polymarket_event_name="",  # Would need market lookup
                    side=SignalSide.YES if trade.side == "YES" else SignalSide.NO,
                    action=SignalAction.BUY if trade.action == "BUY" else SignalAction.SELL,
                    qty=trade.qty,
                    price=trade.price,
                    value_usd=trade.qty * trade.price,
                    meta={
                        "wallet": wallet,
                        "tx_hash": trade.tx_hash,
                        "trade_id": trade.trade_id
                    }
                )
                signals.append(signal)
            except Exception as e:
                logger.warning(f"Failed to create signal from trade: {e}")
        
        return signals
    
    async def poll_gabagool_activity(
        self,
        since_ts: Optional[int] = None
    ) -> List[CopySignal]:
        """
        Poll for new gabagool activity.
        
        Returns new signals since last poll or since_ts.
        """
        cursor = since_ts or self._last_activity_ts
        
        signals = await self.get_gabagool_trades(
            since_ts=cursor,
            limit=50
        )
        
        # Update cursor to latest signal
        if signals:
            self._last_activity_ts = max(s.ts_ms for s in signals)
        
        return signals

