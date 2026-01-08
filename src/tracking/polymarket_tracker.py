"""
Polymarket Wallet Tracker

Tracks a specific Polymarket wallet's trades and positions.
Used for copy trading strategies.
"""

import asyncio
import aiohttp
import json
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from pathlib import Path

from ..logger import StructuredLogger


@dataclass
class PolymarketPosition:
    """A position held on Polymarket."""
    market_id: str
    market_title: str
    outcome: str  # YES or NO
    shares: float
    avg_price: float
    current_price: float
    pnl: float
    pnl_percent: float
    market_slug: str
    last_updated: str


@dataclass
class PolymarketTrade:
    """A trade executed on Polymarket."""
    timestamp: str
    market_id: str
    market_title: str
    side: str  # BUY or SELL
    outcome: str  # YES or NO
    shares: float
    price: float
    value: float
    tx_hash: Optional[str] = None


class PolymarketWalletTracker:
    """
    Tracks a Polymarket wallet's trades and positions.
    
    Uses Polymarket's API and on-chain data to monitor activity.
    """
    
    # Polymarket API endpoints
    GAMMA_API = "https://gamma-api.polymarket.com"
    CLOB_API = "https://clob.polymarket.com"
    DATA_API = "https://data-api.polymarket.com"
    STRAPI_API = "https://strapi-matic.poly.market"
    
    def __init__(self, wallet_address: str, username: str = "unknown"):
        self.logger = StructuredLogger(__name__)
        self.wallet_address = wallet_address.lower()
        self.username = username
        
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Tracked data
        self.positions: Dict[str, PolymarketPosition] = {}
        self.trades: List[PolymarketTrade] = []
        self.last_positions: Dict[str, PolymarketPosition] = {}
        
        # Callbacks for new trades
        self.trade_callbacks = []
    
    async def start(self):
        """Start the tracker."""
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Accept': 'application/json',
        }
        self.session = aiohttp.ClientSession(headers=headers)
        self.logger.info(f"Started tracking Polymarket wallet: {self.wallet_address[:10]}... (@{self.username})")
    
    async def stop(self):
        """Stop the tracker."""
        if self.session:
            await self.session.close()
    
    def on_new_trade(self, callback):
        """Register callback for new trades."""
        self.trade_callbacks.append(callback)
    
    async def fetch_positions(self) -> List[PolymarketPosition]:
        """Fetch current positions for the wallet."""
        # Try multiple API endpoints
        endpoints = [
            (f"{self.GAMMA_API}/user-positions", {"user": self.wallet_address}),
            (f"{self.DATA_API}/positions", {"user": self.wallet_address}),
            (f"{self.CLOB_API}/positions", {"address": self.wallet_address}),
            (f"{self.GAMMA_API}/profiles/{self.wallet_address}/positions", {}),
        ]
        
        for url, params in endpoints:
            try:
                async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        positions = self._parse_positions(data if isinstance(data, list) else data.get('positions', data.get('data', [])))
                        if positions:
                            return positions
                    self.logger.debug(f"Endpoint {url} returned {resp.status}")
            except Exception as e:
                self.logger.debug(f"Endpoint {url} failed: {e}")
                continue
        
        # Try fetching profile with positions
        try:
            profile = await self.fetch_profile()
            if profile and 'positions' in profile:
                return self._parse_positions(profile['positions'])
        except:
            pass
        
        return []
    
    async def fetch_trade_history(self, limit: int = 50) -> List[PolymarketTrade]:
        """Fetch recent trade history for the wallet."""
        # Try multiple endpoints
        endpoints = [
            (f"{self.CLOB_API}/trades", {"maker": self.wallet_address, "limit": limit}),
            (f"{self.CLOB_API}/trades", {"taker": self.wallet_address, "limit": limit}),
            (f"{self.GAMMA_API}/activity/{self.wallet_address}", {"limit": limit}),
            (f"{self.DATA_API}/trades", {"user": self.wallet_address, "limit": limit}),
        ]
        
        all_trades = []
        
        for url, params in endpoints:
            try:
                async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        trades = self._parse_trades(data if isinstance(data, list) else data.get('trades', data.get('data', [])))
                        all_trades.extend(trades)
            except Exception as e:
                self.logger.debug(f"Trade endpoint {url} failed: {e}")
                continue
        
        # Also try activity endpoint
        try:
            alt_trades = await self._fetch_trades_alternative(limit)
            all_trades.extend(alt_trades)
        except:
            pass
        
        # Deduplicate by tx_hash if available
        seen = set()
        unique_trades = []
        for trade in all_trades:
            key = trade.tx_hash or f"{trade.timestamp}_{trade.market_id}_{trade.shares}"
            if key not in seen:
                seen.add(key)
                unique_trades.append(trade)
        
        return unique_trades[:limit]
    
    async def _fetch_trades_alternative(self, limit: int) -> List[PolymarketTrade]:
        """Alternative method to fetch trades."""
        try:
            # Try Gamma API
            url = f"{self.GAMMA_API}/activity"
            params = {"user": self.wallet_address, "limit": limit}
            
            async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return self._parse_activity(data)
                else:
                    return []
        except Exception as e:
            self.logger.debug(f"Alternative trade fetch failed: {e}")
            return []
    
    async def fetch_profile(self) -> Dict:
        """Fetch wallet profile/stats."""
        endpoints = [
            f"{self.GAMMA_API}/users/{self.wallet_address}",
            f"{self.GAMMA_API}/profiles/{self.wallet_address}",
            f"{self.DATA_API}/users/{self.wallet_address}",
            f"{self.CLOB_API}/profile/{self.wallet_address}",
        ]
        
        for url in endpoints:
            try:
                async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data:
                            return data
            except Exception as e:
                self.logger.debug(f"Profile endpoint {url} failed: {e}")
                continue
        
        return {}
    
    def _parse_positions(self, data: List[Dict]) -> List[PolymarketPosition]:
        """Parse positions from API response."""
        positions = []
        
        for item in data:
            try:
                # Extract position data
                market = item.get("market", {})
                
                position = PolymarketPosition(
                    market_id=item.get("conditionId", item.get("marketId", "")),
                    market_title=market.get("question", item.get("title", "Unknown")),
                    outcome=item.get("outcome", "YES"),
                    shares=float(item.get("size", item.get("shares", 0))),
                    avg_price=float(item.get("avgPrice", item.get("averagePrice", 0.5))),
                    current_price=float(item.get("currentPrice", item.get("price", 0.5))),
                    pnl=float(item.get("pnl", 0)),
                    pnl_percent=float(item.get("pnlPercent", 0)),
                    market_slug=market.get("slug", item.get("slug", "")),
                    last_updated=datetime.now().isoformat()
                )
                
                if position.shares > 0:
                    positions.append(position)
            
            except Exception as e:
                self.logger.debug(f"Error parsing position: {e}")
                continue
        
        return positions
    
    def _parse_trades(self, data: List[Dict]) -> List[PolymarketTrade]:
        """Parse trades from API response."""
        trades = []
        
        for item in data:
            try:
                trade = PolymarketTrade(
                    timestamp=item.get("timestamp", datetime.now().isoformat()),
                    market_id=item.get("conditionId", item.get("marketId", "")),
                    market_title=item.get("title", item.get("question", "Unknown")),
                    side=item.get("side", "BUY").upper(),
                    outcome=item.get("outcome", "YES"),
                    shares=float(item.get("size", item.get("shares", 0))),
                    price=float(item.get("price", 0.5)),
                    value=float(item.get("value", 0)),
                    tx_hash=item.get("transactionHash", item.get("txHash", None))
                )
                
                trades.append(trade)
            
            except Exception as e:
                self.logger.debug(f"Error parsing trade: {e}")
                continue
        
        return trades
    
    def _parse_activity(self, data: List[Dict]) -> List[PolymarketTrade]:
        """Parse activity feed as trades."""
        trades = []
        
        for item in data:
            try:
                if item.get("type") in ["BUY", "SELL", "trade", "order"]:
                    trade = PolymarketTrade(
                        timestamp=item.get("timestamp", datetime.now().isoformat()),
                        market_id=item.get("conditionId", item.get("marketId", "")),
                        market_title=item.get("title", item.get("question", "Unknown")),
                        side=item.get("type", "BUY").upper(),
                        outcome=item.get("outcome", "YES"),
                        shares=float(item.get("size", item.get("amount", 0))),
                        price=float(item.get("price", 0.5)),
                        value=float(item.get("value", 0)),
                        tx_hash=item.get("transactionHash", None)
                    )
                    
                    if trade.side in ["BUY", "SELL"]:
                        trades.append(trade)
            
            except Exception as e:
                self.logger.debug(f"Error parsing activity: {e}")
                continue
        
        return trades
    
    async def check_for_new_trades(self) -> List[PolymarketTrade]:
        """Check for new trades since last check."""
        # Get current positions
        current_positions = await self.fetch_positions()
        
        new_trades = []
        
        # Compare with last known positions
        for pos in current_positions:
            key = f"{pos.market_id}_{pos.outcome}"
            
            if key in self.last_positions:
                old_pos = self.last_positions[key]
                
                # Check for changes in share count
                share_diff = pos.shares - old_pos.shares
                
                if abs(share_diff) > 0.01:  # Significant change
                    trade = PolymarketTrade(
                        timestamp=datetime.now().isoformat(),
                        market_id=pos.market_id,
                        market_title=pos.market_title,
                        side="BUY" if share_diff > 0 else "SELL",
                        outcome=pos.outcome,
                        shares=abs(share_diff),
                        price=pos.current_price,
                        value=abs(share_diff) * pos.current_price
                    )
                    
                    new_trades.append(trade)
                    self.trades.append(trade)
                    
                    # Notify callbacks
                    for callback in self.trade_callbacks:
                        await callback(trade)
            
            else:
                # New position opened
                if pos.shares > 0.01:
                    trade = PolymarketTrade(
                        timestamp=datetime.now().isoformat(),
                        market_id=pos.market_id,
                        market_title=pos.market_title,
                        side="BUY",
                        outcome=pos.outcome,
                        shares=pos.shares,
                        price=pos.avg_price,
                        value=pos.shares * pos.avg_price
                    )
                    
                    new_trades.append(trade)
                    self.trades.append(trade)
                    
                    for callback in self.trade_callbacks:
                        await callback(trade)
        
        # Check for closed positions
        for key, old_pos in self.last_positions.items():
            found = False
            for pos in current_positions:
                if f"{pos.market_id}_{pos.outcome}" == key:
                    found = True
                    break
            
            if not found and old_pos.shares > 0.01:
                # Position closed
                trade = PolymarketTrade(
                    timestamp=datetime.now().isoformat(),
                    market_id=old_pos.market_id,
                    market_title=old_pos.market_title,
                    side="SELL",
                    outcome=old_pos.outcome,
                    shares=old_pos.shares,
                    price=old_pos.current_price,
                    value=old_pos.shares * old_pos.current_price
                )
                
                new_trades.append(trade)
                self.trades.append(trade)
                
                for callback in self.trade_callbacks:
                    await callback(trade)
        
        # Update last positions
        self.last_positions = {f"{p.market_id}_{p.outcome}": p for p in current_positions}
        self.positions = {f"{p.market_id}_{p.outcome}": p for p in current_positions}
        
        return new_trades
    
    def get_portfolio_summary(self) -> Dict:
        """Get summary of current portfolio."""
        if not self.positions:
            return {
                "total_positions": 0,
                "total_value": 0,
                "total_pnl": 0,
                "positions": []
            }
        
        total_value = sum(p.shares * p.current_price for p in self.positions.values())
        total_pnl = sum(p.pnl for p in self.positions.values())
        
        return {
            "total_positions": len(self.positions),
            "total_value": total_value,
            "total_pnl": total_pnl,
            "positions": [asdict(p) for p in self.positions.values()]
        }

