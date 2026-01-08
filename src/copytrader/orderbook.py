"""
Real Orderbook Data Fetching
Fetches ACTUAL prices from Polymarket and Kalshi orderbooks
"""
import aiohttp
import asyncio
from dataclasses import dataclass
from typing import Optional, List, Tuple
from datetime import datetime
import json

@dataclass
class OrderbookLevel:
    """Single price level in orderbook"""
    price: float
    size: float  # In shares/contracts
    
@dataclass
class OrderbookSnapshot:
    """Full orderbook snapshot"""
    venue: str
    asset_id: str
    timestamp: float
    
    bids: List[OrderbookLevel]  # Sorted by price descending (best first)
    asks: List[OrderbookLevel]  # Sorted by price ascending (best first)
    
    last_trade_price: Optional[float] = None
    
    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0].price if self.bids else None
    
    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0].price if self.asks else None
    
    @property
    def mid_price(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2
        return self.last_trade_price
    
    @property
    def spread(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None
    
    @property
    def spread_bps(self) -> Optional[float]:
        if self.spread and self.mid_price:
            return (self.spread / self.mid_price) * 10000
        return None
    
    def liquidity_at_price(self, side: str, price: float) -> float:
        """Get total liquidity available at or better than price"""
        total = 0.0
        if side == "BUY":
            # For buying, we take from asks
            for level in self.asks:
                if level.price <= price:
                    total += level.size * level.price
                else:
                    break
        else:
            # For selling, we hit bids
            for level in self.bids:
                if level.price >= price:
                    total += level.size * level.price
                else:
                    break
        return total

class OrderbookFetcher:
    """Fetches real orderbook data from venues"""
    
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self._cache: dict = {}
        self._cache_ttl = 0.5  # 500ms cache
        
    async def get_polymarket_orderbook(self, token_id: str) -> Optional[OrderbookSnapshot]:
        """Fetch REAL orderbook from Polymarket CLOB"""
        cache_key = f"poly_{token_id}"
        
        # Check cache
        if cache_key in self._cache:
            cached, ts = self._cache[cache_key]
            if (datetime.now().timestamp() - ts) < self._cache_ttl:
                return cached
        
        try:
            url = f"https://clob.polymarket.com/book?token_id={token_id}"
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=2)) as resp:
                if resp.status != 200:
                    return None
                    
                data = await resp.json()
                
                # Parse bids (highest first)
                bids = []
                for b in data.get('bids', []):
                    bids.append(OrderbookLevel(
                        price=float(b['price']),
                        size=float(b['size'])
                    ))
                # Sort descending by price
                bids.sort(key=lambda x: x.price, reverse=True)
                
                # Parse asks (lowest first)
                asks = []
                for a in data.get('asks', []):
                    asks.append(OrderbookLevel(
                        price=float(a['price']),
                        size=float(a['size'])
                    ))
                # Sort ascending by price
                asks.sort(key=lambda x: x.price)
                
                snapshot = OrderbookSnapshot(
                    venue="POLYMARKET",
                    asset_id=token_id,
                    timestamp=datetime.now().timestamp(),
                    bids=bids,
                    asks=asks,
                    last_trade_price=float(data.get('last_trade_price', 0)) if data.get('last_trade_price') else None
                )
                
                # Cache it
                self._cache[cache_key] = (snapshot, datetime.now().timestamp())
                
                return snapshot
                
        except Exception as e:
            return None
    
    async def get_execution_price(self, token_id: str, side: str, size_usd: float) -> Tuple[Optional[float], float, float]:
        """
        Get realistic execution price for a given order size
        
        Returns:
            (price, fill_rate, available_liquidity_usd)
        """
        book = await self.get_polymarket_orderbook(token_id)
        if not book:
            return None, 0.0, 0.0
        
        if side == "BUY":
            levels = book.asks
            if not levels:
                # No asks - use last trade + spread estimate
                if book.last_trade_price:
                    return book.last_trade_price * 1.01, 1.0, 0.0
                return None, 0.0, 0.0
        else:
            levels = book.bids
            if not levels:
                if book.last_trade_price:
                    return book.last_trade_price * 0.99, 1.0, 0.0
                return None, 0.0, 0.0
        
        # Walk the book to find execution price
        remaining = size_usd
        total_cost = 0.0
        total_shares = 0.0
        available_liquidity = sum(l.size * l.price for l in levels)
        
        for level in levels:
            level_liquidity = level.size * level.price
            
            if remaining <= level_liquidity:
                # Can fill entirely at this level
                shares_at_level = remaining / level.price
                total_shares += shares_at_level
                total_cost += remaining
                remaining = 0
                break
            else:
                # Take all liquidity at this level
                total_shares += level.size
                total_cost += level_liquidity
                remaining -= level_liquidity
        
        if total_shares == 0:
            return None, 0.0, available_liquidity
        
        # Volume-weighted average price
        vwap = total_cost / total_shares
        fill_rate = (size_usd - remaining) / size_usd if size_usd > 0 else 0
        
        return vwap, fill_rate, available_liquidity
    
    async def get_market_info(self, slug: str) -> Optional[dict]:
        """Get market metadata from Polymarket"""
        try:
            url = f"https://gamma-api.polymarket.com/markets?slug={slug}"
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=2)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, list) and data:
                        return data[0]
        except:
            pass
        return None

