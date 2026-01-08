"""
Fill Model - Simulates order execution.

Provides realistic fill simulation based on:
- Orderbook depth
- Latency
- Slippage
"""

import uuid
from datetime import datetime
from typing import List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from ..adapters.base import Orderbook, OrderbookLevel
from ..config import get_settings


class FillStatus(str, Enum):
    """Fill status."""
    FILLED = "filled"
    PARTIAL = "partial"
    MISSED = "missed"


@dataclass
class FillResult:
    """Result of a simulated fill."""
    order_id: str
    status: FillStatus
    
    requested_qty: float
    filled_qty: float
    
    # Pricing
    limit_price: float
    avg_fill_price: Optional[float]
    
    # Breakdown by level
    fills: List[Tuple[float, float, int]]  # (price, qty, level_idx)
    
    # Costs
    total_cost: float
    total_fee: float
    
    # Metrics
    slippage_bps: float
    latency_ms: int
    
    # Timestamps
    created_at: datetime
    filled_at: Optional[datetime]
    
    @property
    def is_complete(self) -> bool:
        return self.status == FillStatus.FILLED
    
    @property
    def unfilled_qty(self) -> float:
        return self.requested_qty - self.filled_qty


class FillModel:
    """
    Simulates order fills against orderbook.
    
    Models:
    - Limit order matching
    - Partial fills
    - Slippage based on depth
    - Fees
    """
    
    def __init__(
        self,
        fee_bps: Optional[int] = None,
        slippage_buffer_bps: Optional[int] = None,
        default_latency_ms: Optional[int] = None
    ):
        """
        Initialize fill model.
        
        Args:
            fee_bps: Fee in basis points (default from settings)
            slippage_buffer_bps: Slippage buffer in bps
            default_latency_ms: Default simulated latency
        """
        settings = get_settings()
        self.fee_bps = fee_bps or settings.kalshi_fee_bps
        self.slippage_buffer_bps = slippage_buffer_bps or settings.slippage_bps_buffer
        self.default_latency_ms = default_latency_ms or settings.default_latency_ms
    
    def simulate_fill(
        self,
        orderbook: Orderbook,
        side: str,
        action: str,
        qty: float,
        limit_price: float,
        latency_ms: Optional[int] = None
    ) -> FillResult:
        """
        Simulate filling an order against orderbook.
        
        Args:
            orderbook: Current orderbook snapshot
            side: YES or NO
            action: BUY or SELL
            qty: Quantity to fill
            limit_price: Limit price (0-1)
            latency_ms: Simulated latency
            
        Returns:
            FillResult with fill details
        """
        order_id = str(uuid.uuid4())[:16]
        latency = latency_ms or self.default_latency_ms
        created_at = datetime.utcnow()
        
        # Get relevant book side
        if side == "YES":
            levels = orderbook.yes_asks if action == "BUY" else orderbook.yes_bids
        else:
            levels = orderbook.no_asks if action == "BUY" else orderbook.no_bids
        
        # Apply slippage buffer to limit
        buffer = self.slippage_buffer_bps / 10000
        adjusted_limit = limit_price + buffer if action == "BUY" else limit_price - buffer
        
        # Simulate fills
        fills = []
        remaining = qty
        total_value = 0.0
        total_qty = 0.0
        
        for i, level in enumerate(levels):
            # Check if level is within limit
            if action == "BUY" and level.price > adjusted_limit:
                break
            if action == "SELL" and level.price < adjusted_limit:
                break
            
            fill_qty = min(remaining, level.qty)
            fills.append((level.price, fill_qty, i))
            total_value += fill_qty * level.price
            total_qty += fill_qty
            remaining -= fill_qty
            
            if remaining <= 0:
                break
        
        # Calculate results
        avg_price = total_value / total_qty if total_qty > 0 else None
        fee = total_value * (self.fee_bps / 10000) if total_value > 0 else 0
        
        # Calculate slippage
        slippage_bps = 0
        if avg_price and limit_price > 0:
            slippage = (avg_price - limit_price) / limit_price if action == "BUY" else (limit_price - avg_price) / limit_price
            slippage_bps = slippage * 10000
        
        # Determine status
        if total_qty >= qty:
            status = FillStatus.FILLED
        elif total_qty > 0:
            status = FillStatus.PARTIAL
        else:
            status = FillStatus.MISSED
        
        return FillResult(
            order_id=order_id,
            status=status,
            requested_qty=qty,
            filled_qty=total_qty,
            limit_price=limit_price,
            avg_fill_price=avg_price,
            fills=fills,
            total_cost=total_value + fee,
            total_fee=fee,
            slippage_bps=slippage_bps,
            latency_ms=latency,
            created_at=created_at,
            filled_at=datetime.utcnow() if total_qty > 0 else None
        )
    
    def simulate_market_order(
        self,
        orderbook: Orderbook,
        side: str,
        action: str,
        qty: float,
        latency_ms: Optional[int] = None
    ) -> FillResult:
        """
        Simulate a market order (fill at any price).
        """
        # Market order = very high/low limit
        limit_price = 1.0 if action == "BUY" else 0.0
        return self.simulate_fill(orderbook, side, action, qty, limit_price, latency_ms)
    
    def estimate_fill_probability(
        self,
        orderbook: Orderbook,
        side: str,
        action: str,
        qty: float,
        limit_price: float
    ) -> float:
        """
        Estimate probability of filling at limit.
        
        Simple heuristic based on book depth.
        """
        if side == "YES":
            levels = orderbook.yes_asks if action == "BUY" else orderbook.yes_bids
        else:
            levels = orderbook.no_asks if action == "BUY" else orderbook.no_bids
        
        if not levels:
            return 0.0
        
        # Sum available liquidity at or better than limit
        available = 0.0
        for level in levels:
            if action == "BUY" and level.price <= limit_price:
                available += level.qty
            elif action == "SELL" and level.price >= limit_price:
                available += level.qty
        
        if available >= qty:
            return 1.0
        elif available > 0:
            return available / qty
        
        return 0.0

