"""
Base adapter interface.

All exchange adapters implement this interface for consistency.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class AdapterConfig:
    """Base configuration for adapters."""
    retry_attempts: int = 3
    retry_delay_ms: int = 1000
    timeout_ms: int = 10000
    
    
@dataclass
class MarketSnapshot:
    """Standardized market snapshot across venues."""
    market_id: str
    ticker: str
    title: str
    venue: str
    
    # Current prices
    yes_bid: Optional[float] = None
    yes_ask: Optional[float] = None
    no_bid: Optional[float] = None
    no_ask: Optional[float] = None
    last_price: Optional[float] = None
    
    # Volume
    volume: float = 0.0
    open_interest: float = 0.0
    
    # Timing
    expiry_ts: Optional[int] = None
    
    # Status
    status: str = "active"
    
    # Metadata
    underlying: Optional[str] = None
    strike: Optional[float] = None
    
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


@dataclass
class OrderbookLevel:
    """Single orderbook level."""
    price: float
    qty: float


@dataclass
class Orderbook:
    """Orderbook snapshot."""
    market_id: str
    venue: str
    timestamp: datetime
    
    yes_bids: List[OrderbookLevel]  # Sorted best to worst
    yes_asks: List[OrderbookLevel]  # Sorted best to worst
    no_bids: List[OrderbookLevel]
    no_asks: List[OrderbookLevel]
    
    @property
    def yes_best_bid(self) -> Optional[float]:
        return self.yes_bids[0].price if self.yes_bids else None
    
    @property
    def yes_best_ask(self) -> Optional[float]:
        return self.yes_asks[0].price if self.yes_asks else None
    
    @property
    def yes_spread(self) -> Optional[float]:
        if self.yes_best_bid and self.yes_best_ask:
            return self.yes_best_ask - self.yes_best_bid
        return None
    
    def get_fill_price_yes(self, qty: float, side: str = "BUY") -> Optional[float]:
        """
        Get estimated fill price for YES side.
        
        Args:
            qty: Quantity to fill
            side: BUY (lift asks) or SELL (hit bids)
            
        Returns:
            VWAP fill price or None if insufficient liquidity
        """
        levels = self.yes_asks if side == "BUY" else self.yes_bids
        return self._calculate_fill_price(levels, qty)
    
    def get_fill_price_no(self, qty: float, side: str = "BUY") -> Optional[float]:
        """Get estimated fill price for NO side."""
        levels = self.no_asks if side == "BUY" else self.no_bids
        return self._calculate_fill_price(levels, qty)
    
    def _calculate_fill_price(self, levels: List[OrderbookLevel], qty: float) -> Optional[float]:
        """Calculate VWAP for filling quantity across levels."""
        if not levels:
            return None
        
        remaining = qty
        total_value = 0.0
        total_filled = 0.0
        
        for level in levels:
            fill_qty = min(remaining, level.qty)
            total_value += fill_qty * level.price
            total_filled += fill_qty
            remaining -= fill_qty
            
            if remaining <= 0:
                break
        
        if total_filled == 0:
            return None
        
        return total_value / total_filled


@dataclass
class Trade:
    """Standardized trade record."""
    trade_id: str
    market_id: str
    venue: str
    timestamp: datetime
    
    side: str  # YES, NO
    action: str  # BUY, SELL
    qty: float
    price: float
    
    maker: Optional[str] = None
    taker: Optional[str] = None
    tx_hash: Optional[str] = None


@dataclass
class Position:
    """Position held on a venue."""
    market_id: str
    venue: str
    
    yes_qty: float = 0.0
    no_qty: float = 0.0
    yes_avg_cost: float = 0.0
    no_avg_cost: float = 0.0


class BaseAdapter(ABC):
    """
    Abstract base adapter for exchange integrations.
    
    All venue adapters must implement this interface.
    """
    
    def __init__(self, config: Optional[AdapterConfig] = None):
        self.config = config or AdapterConfig()
        self._connected = False
    
    @property
    @abstractmethod
    def venue_name(self) -> str:
        """Get venue identifier."""
        pass
    
    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the venue."""
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the venue."""
        pass
    
    @property
    def is_connected(self) -> bool:
        """Check if connected."""
        return self._connected
    
    # === Market Data ===
    
    @abstractmethod
    async def get_markets(self, **filters) -> List[MarketSnapshot]:
        """Get available markets."""
        pass
    
    @abstractmethod
    async def get_market(self, market_id: str) -> Optional[MarketSnapshot]:
        """Get a specific market."""
        pass
    
    @abstractmethod
    async def get_orderbook(self, market_id: str) -> Optional[Orderbook]:
        """Get orderbook for a market."""
        pass
    
    # === Trade History ===
    
    @abstractmethod
    async def get_trades(
        self,
        market_id: Optional[str] = None,
        wallet: Optional[str] = None,
        since_ts: Optional[int] = None,
        limit: int = 100
    ) -> List[Trade]:
        """Get trade history."""
        pass
    
    # === Positions ===
    
    @abstractmethod
    async def get_positions(self, wallet: Optional[str] = None) -> List[Position]:
        """Get current positions."""
        pass

