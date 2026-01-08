"""
Realistic Trade Execution Engine
Simulates ALL real-world costs and constraints
"""
from dataclasses import dataclass, field
from typing import Optional, Tuple
from datetime import datetime
import time

from .config import CONFIG, PolymarketFees, KalshiFees
from .orderbook import OrderbookFetcher, OrderbookSnapshot

@dataclass
class ExecutionResult:
    """Result of a trade execution attempt"""
    success: bool
    venue: str
    
    # What we tried to do
    requested_side: str
    requested_size_usd: float
    
    # What actually happened
    executed_qty: float = 0.0
    executed_price: float = 0.0
    fill_rate: float = 0.0
    
    # Costs breakdown
    trade_value: float = 0.0
    trading_fee: float = 0.0
    gas_fee: float = 0.0
    slippage_cost: float = 0.0
    total_cost: float = 0.0
    
    # Comparison to gabagool
    gabagool_price: float = 0.0
    slippage_vs_gabagool_pct: float = 0.0
    
    # Meta
    latency_ms: int = 0
    reject_reason: str = ""
    orderbook_spread_bps: float = 0.0
    available_liquidity: float = 0.0
    
    @property
    def effective_price(self) -> float:
        """Price including all fees"""
        if self.executed_qty <= 0:
            return 0.0
        return self.total_cost / self.executed_qty


class ExecutionEngine:
    """
    Simulates realistic trade execution with ALL costs
    """
    
    def __init__(self, orderbook_fetcher: OrderbookFetcher):
        self.orderbook = orderbook_fetcher
        
    async def execute_polymarket_buy(
        self,
        token_id: str,
        gabagool_price: float,
        target_size_usd: float,
        latency_ms: int
    ) -> ExecutionResult:
        """
        Execute a BUY on Polymarket with realistic costs
        
        Costs included:
        1. Actual orderbook price (not gabagool's price)
        2. Price impact from walking the book
        3. 2% taker fee
        4. Gas fee (~$0.05)
        5. Slippage from latency
        """
        result = ExecutionResult(
            success=False,
            venue="POLYMARKET",
            requested_side="BUY",
            requested_size_usd=target_size_usd,
            gabagool_price=gabagool_price,
            latency_ms=latency_ms
        )
        
        # Get real orderbook
        exec_price, fill_rate, liquidity = await self.orderbook.get_execution_price(
            token_id, "BUY", target_size_usd
        )
        
        result.available_liquidity = liquidity
        
        if exec_price is None:
            result.reject_reason = "No orderbook data"
            return result
        
        # Add latency-based price drift
        latency_seconds = latency_ms / 1000.0
        latency_drift = latency_seconds * (CONFIG.execution.LATENCY_DRIFT_BPS_PER_SEC / 10000)
        exec_price *= (1 + latency_drift)
        
        # Calculate slippage vs gabagool
        if gabagool_price > 0:
            slippage_pct = (exec_price - gabagool_price) / gabagool_price
            result.slippage_vs_gabagool_pct = slippage_pct
            
            # Check slippage limit
            if slippage_pct > CONFIG.risk.MAX_SLIPPAGE_PCT:
                result.reject_reason = f"Slippage too high: {slippage_pct*100:.1f}%"
                return result
        
        # Calculate fill
        actual_size_usd = target_size_usd * fill_rate
        if actual_size_usd < CONFIG.poly_fees.MIN_ORDER_USD:
            result.reject_reason = f"Fill too small: ${actual_size_usd:.2f}"
            return result
        
        # Calculate shares
        shares = actual_size_usd / exec_price
        
        # Calculate costs
        trade_value = shares * exec_price
        trading_fee = trade_value * CONFIG.poly_fees.TAKER_FEE
        gas_fee = CONFIG.poly_fees.GAS_FEE_USD
        slippage_cost = shares * (exec_price - gabagool_price) if gabagool_price > 0 else 0
        
        total_cost = trade_value + trading_fee + gas_fee
        
        # Populate result
        result.success = True
        result.executed_qty = shares
        result.executed_price = exec_price
        result.fill_rate = fill_rate
        result.trade_value = trade_value
        result.trading_fee = trading_fee
        result.gas_fee = gas_fee
        result.slippage_cost = slippage_cost
        result.total_cost = total_cost
        
        return result
    
    async def execute_polymarket_sell(
        self,
        token_id: str,
        qty: float,
        latency_ms: int
    ) -> ExecutionResult:
        """Execute a SELL on Polymarket"""
        result = ExecutionResult(
            success=False,
            venue="POLYMARKET",
            requested_side="SELL",
            requested_size_usd=qty,  # Approximate
            latency_ms=latency_ms
        )
        
        # Estimate size in USD
        book = await self.orderbook.get_polymarket_orderbook(token_id)
        if not book or not book.best_bid:
            result.reject_reason = "No bid liquidity"
            return result
        
        size_usd = qty * book.best_bid
        exec_price, fill_rate, liquidity = await self.orderbook.get_execution_price(
            token_id, "SELL", size_usd
        )
        
        if exec_price is None:
            result.reject_reason = "No orderbook data"
            return result
        
        # Latency drift (price goes against us)
        latency_seconds = latency_ms / 1000.0
        latency_drift = latency_seconds * (CONFIG.execution.LATENCY_DRIFT_BPS_PER_SEC / 10000)
        exec_price *= (1 - latency_drift)  # Price drops when selling
        
        # Calculate proceeds
        actual_qty = qty * fill_rate
        gross_proceeds = actual_qty * exec_price
        trading_fee = gross_proceeds * CONFIG.poly_fees.TAKER_FEE
        gas_fee = CONFIG.poly_fees.GAS_FEE_USD
        
        net_proceeds = gross_proceeds - trading_fee - gas_fee
        
        result.success = True
        result.executed_qty = actual_qty
        result.executed_price = exec_price
        result.fill_rate = fill_rate
        result.trade_value = gross_proceeds
        result.trading_fee = trading_fee
        result.gas_fee = gas_fee
        result.total_cost = trading_fee + gas_fee  # Cost is fees
        
        return result
    
    async def execute_kalshi_buy(
        self,
        token_id: str,
        gabagool_price: float,
        target_size_usd: float,
        latency_ms: int
    ) -> ExecutionResult:
        """
        Simulate Kalshi execution
        
        Note: We don't have real Kalshi orderbook access, so we estimate
        based on Polymarket price + typical Kalshi spread
        """
        result = ExecutionResult(
            success=False,
            venue="KALSHI",
            requested_side="BUY",
            requested_size_usd=target_size_usd,
            gabagool_price=gabagool_price,
            latency_ms=latency_ms
        )
        
        # Get Polymarket price as reference
        poly_price, _, _ = await self.orderbook.get_execution_price(
            token_id, "BUY", target_size_usd
        )
        
        if poly_price is None:
            # Use gabagool price + estimated spread
            poly_price = gabagool_price * 1.02
        
        # Kalshi typically has wider spreads
        kalshi_spread_premium = 0.01  # 1% wider
        exec_price = poly_price * (1 + kalshi_spread_premium)
        
        # Additional latency for cross-platform
        extra_latency_ms = 2000  # 2 seconds to switch platforms
        total_latency = latency_ms + extra_latency_ms
        latency_drift = (total_latency / 1000.0) * (CONFIG.execution.LATENCY_DRIFT_BPS_PER_SEC / 10000)
        exec_price *= (1 + latency_drift)
        
        # Slippage check
        if gabagool_price > 0:
            slippage_pct = (exec_price - gabagool_price) / gabagool_price
            result.slippage_vs_gabagool_pct = slippage_pct
            
            if slippage_pct > CONFIG.risk.MAX_SLIPPAGE_PCT:
                result.reject_reason = f"Slippage too high: {slippage_pct*100:.1f}%"
                return result
        
        # Kalshi contracts
        contracts = target_size_usd / exec_price
        trade_value = contracts * exec_price
        
        # Kalshi fee structure (exchange fee on trade)
        exchange_fee = trade_value * CONFIG.kalshi_fees.EXCHANGE_FEE
        total_cost = trade_value + exchange_fee
        
        result.success = True
        result.executed_qty = contracts
        result.executed_price = exec_price
        result.fill_rate = 1.0  # Kalshi usually fills fully
        result.trade_value = trade_value
        result.trading_fee = exchange_fee
        result.gas_fee = 0.0  # No gas on Kalshi
        result.total_cost = total_cost
        result.latency_ms = total_latency
        
        return result
    
    async def execute_kalshi_sell(
        self,
        token_id: str,
        qty: float,
        entry_price: float,
        latency_ms: int
    ) -> ExecutionResult:
        """Simulate Kalshi sell"""
        result = ExecutionResult(
            success=False,
            venue="KALSHI",
            requested_side="SELL",
            requested_size_usd=qty * entry_price,
            latency_ms=latency_ms
        )
        
        # Get reference price
        poly_book = await self.orderbook.get_polymarket_orderbook(token_id)
        if poly_book and poly_book.best_bid:
            exec_price = poly_book.best_bid * 0.99  # Kalshi worse
        else:
            exec_price = entry_price * 0.98
        
        # Latency
        latency_drift = (latency_ms / 1000.0) * (CONFIG.execution.LATENCY_DRIFT_BPS_PER_SEC / 10000)
        exec_price *= (1 - latency_drift)
        
        gross = qty * exec_price
        pnl = qty * (exec_price - entry_price)
        
        # Kalshi fees on profit
        profit_fee = max(0, pnl * CONFIG.kalshi_fees.PROFIT_FEE_RATE)
        
        result.success = True
        result.executed_qty = qty
        result.executed_price = exec_price
        result.fill_rate = 1.0
        result.trade_value = gross
        result.trading_fee = profit_fee
        result.total_cost = profit_fee
        
        return result

