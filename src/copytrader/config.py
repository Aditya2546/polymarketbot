"""
Production Configuration - ALL Real-World Cost Parameters
"""
from dataclasses import dataclass
from typing import Dict

@dataclass(frozen=True)
class PolymarketFees:
    """Polymarket fee structure (as of 2024)"""
    TAKER_FEE: float = 0.02      # 2% taker fee on trade value
    MAKER_FEE: float = 0.0       # 0% maker fee
    GAS_FEE_USD: float = 0.05    # ~$0.05 per trade on Polygon (variable)
    MIN_ORDER_USD: float = 1.0   # Minimum order size
    
@dataclass(frozen=True)
class KalshiFees:
    """Kalshi fee structure"""
    # Kalshi charges on PROFIT, not on trade value
    PROFIT_FEE_RATE: float = 0.07    # 7% of profit
    EXCHANGE_FEE: float = 0.01       # 1% exchange fee per contract
    MIN_ORDER_USD: float = 1.0       # Minimum order
    CONTRACT_SIZE: float = 1.0       # $1 per contract at settlement

@dataclass(frozen=True)
class ExecutionParams:
    """Realistic execution parameters"""
    # Slippage components
    BASE_SPREAD_BPS: int = 50        # 0.5% average bid-ask spread
    MARKET_IMPACT_BPS: int = 100     # 1% impact from gabagool's trade
    LATENCY_DRIFT_BPS_PER_SEC: int = 10  # 0.1% per second of latency
    
    # Fill probability
    PARTIAL_FILL_PROB: float = 0.10  # 10% chance of partial fill
    MIN_FILL_RATE: float = 0.5       # Minimum 50% fill on partials
    
    # Liquidity thresholds
    THIN_LIQUIDITY_THRESHOLD: float = 100.0  # $100 = thin market
    
    # Rejection
    ORDER_REJECT_PROB: float = 0.01  # 1% random rejection

@dataclass(frozen=True)
class RiskParams:
    """Risk management parameters"""
    # Position limits
    MAX_POSITION_PCT: float = 0.15    # Max 15% of balance per position
    MAX_OPEN_POSITIONS: int = 30      # Maximum concurrent positions
    MIN_POSITION_USD: float = 2.0     # Minimum position size
    MAX_POSITION_USD: float = 20.0    # Maximum position size
    
    # Slippage limits
    MAX_SLIPPAGE_PCT: float = 0.10    # Skip if slippage > 10%
    
    # Drawdown limits
    MAX_DAILY_DRAWDOWN_PCT: float = 0.20  # Stop if down 20% in a day
    
    # Balance reserve
    BALANCE_RESERVE_PCT: float = 0.10  # Keep 10% as reserve

@dataclass(frozen=True)
class Config:
    """Master configuration"""
    poly_fees: PolymarketFees = PolymarketFees()
    kalshi_fees: KalshiFees = KalshiFees()
    execution: ExecutionParams = ExecutionParams()
    risk: RiskParams = RiskParams()
    
    # Target wallet
    GABAGOOL_ADDRESS: str = "0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d"
    
    # Starting capital
    STARTING_BALANCE: float = 200.0

# Global config instance
CONFIG = Config()

