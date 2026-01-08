"""Tests for simulation components."""

import pytest
from datetime import datetime

from src.gabagool_mirror.simulation.fill_model import (
    FillModel, FillResult, FillStatus
)
from src.gabagool_mirror.simulation.position import (
    SimulatedPosition, PositionLedger
)
from src.gabagool_mirror.adapters.base import Orderbook, OrderbookLevel


class TestFillModel:
    """Test orderbook fill simulation."""
    
    @pytest.fixture
    def simple_orderbook(self):
        """Create a simple orderbook for testing."""
        return Orderbook(
            market_id="test_market",
            venue="KALSHI",
            timestamp=datetime.utcnow(),
            yes_bids=[
                OrderbookLevel(price=0.45, qty=100),
                OrderbookLevel(price=0.44, qty=200),
            ],
            yes_asks=[
                OrderbookLevel(price=0.50, qty=100),
                OrderbookLevel(price=0.52, qty=200),
                OrderbookLevel(price=0.55, qty=300),
            ],
            no_bids=[
                OrderbookLevel(price=0.48, qty=150),
            ],
            no_asks=[
                OrderbookLevel(price=0.52, qty=100),
            ]
        )
    
    def test_full_fill_at_top_of_book(self, simple_orderbook):
        """Test full fill at top of book."""
        model = FillModel(fee_bps=70, slippage_buffer_bps=0)
        
        result = model.simulate_fill(
            orderbook=simple_orderbook,
            side="YES",
            action="BUY",
            qty=50,  # Less than 100 available at 0.50
            limit_price=0.55
        )
        
        assert result.status == FillStatus.FILLED
        assert result.filled_qty == 50
        assert result.avg_fill_price == 0.50
    
    def test_partial_fill_across_levels(self, simple_orderbook):
        """Test filling across multiple price levels."""
        model = FillModel(fee_bps=70, slippage_buffer_bps=0)
        
        result = model.simulate_fill(
            orderbook=simple_orderbook,
            side="YES",
            action="BUY",
            qty=250,  # 100 at 0.50 + 150 at 0.52
            limit_price=0.53
        )
        
        assert result.status == FillStatus.FILLED
        assert result.filled_qty == 250
        # VWAP = (100*0.50 + 150*0.52) / 250 = 0.512
        assert abs(result.avg_fill_price - 0.512) < 0.001
    
    def test_partial_fill_hits_limit(self, simple_orderbook):
        """Test partial fill when hitting limit price."""
        model = FillModel(fee_bps=70, slippage_buffer_bps=0)
        
        result = model.simulate_fill(
            orderbook=simple_orderbook,
            side="YES",
            action="BUY",
            qty=500,  # Want 500, but only 100 at 0.50
            limit_price=0.50  # Tight limit
        )
        
        assert result.status == FillStatus.PARTIAL
        assert result.filled_qty == 100
        assert result.unfilled_qty == 400
    
    def test_missed_fill_no_liquidity(self, simple_orderbook):
        """Test missed fill when no liquidity available."""
        model = FillModel(fee_bps=70, slippage_buffer_bps=0)
        
        result = model.simulate_fill(
            orderbook=simple_orderbook,
            side="YES",
            action="BUY",
            qty=100,
            limit_price=0.40  # Below all asks
        )
        
        assert result.status == FillStatus.MISSED
        assert result.filled_qty == 0
    
    def test_slippage_buffer_extends_limit(self, simple_orderbook):
        """Test slippage buffer extends effective limit."""
        model = FillModel(fee_bps=70, slippage_buffer_bps=300)  # 3% buffer
        
        result = model.simulate_fill(
            orderbook=simple_orderbook,
            side="YES",
            action="BUY",
            qty=100,
            limit_price=0.50  # With 3% buffer = 0.53 effective
        )
        
        assert result.status == FillStatus.FILLED
        assert result.filled_qty == 100
    
    def test_fee_included_in_cost(self, simple_orderbook):
        """Test fees are included in total cost."""
        model = FillModel(fee_bps=100)  # 1% fee
        
        result = model.simulate_fill(
            orderbook=simple_orderbook,
            side="YES",
            action="BUY",
            qty=100,
            limit_price=0.55
        )
        
        # Cost = 100 * 0.50 = $50
        # Fee = $50 * 0.01 = $0.50
        # Total = $50.50
        expected_cost = 100 * 0.50 * 1.01
        assert abs(result.total_cost - expected_cost) < 0.01


class TestSimulatedPosition:
    """Test position tracking."""
    
    def test_add_yes_fill(self):
        """Test adding YES fill to position."""
        pos = SimulatedPosition(market_id="test", venue="KALSHI")
        
        pos.add_fill(side="YES", qty=100, cost=50)
        
        assert pos.yes_qty == 100
        assert pos.yes_total_cost == 50
        assert pos.yes_avg_cost == 0.50
        assert pos.no_qty == 0
    
    def test_add_multiple_fills_vwap(self):
        """Test VWAP calculation with multiple fills."""
        pos = SimulatedPosition(market_id="test", venue="KALSHI")
        
        pos.add_fill(side="YES", qty=100, cost=50)  # 100 @ 0.50
        pos.add_fill(side="YES", qty=100, cost=60)  # 100 @ 0.60
        
        assert pos.yes_qty == 200
        assert pos.yes_total_cost == 110
        assert pos.yes_avg_cost == 0.55  # VWAP
    
    def test_hedge_detection(self):
        """Test hedged position detection."""
        pos = SimulatedPosition(market_id="test", venue="KALSHI")
        
        assert not pos.is_hedged
        
        pos.add_fill(side="YES", qty=100, cost=50)
        assert not pos.is_hedged
        
        pos.add_fill(side="NO", qty=100, cost=45)
        assert pos.is_hedged
    
    def test_hedge_locked_edge(self):
        """Test locked edge calculation for hedged position."""
        pos = SimulatedPosition(market_id="test", venue="KALSHI")
        
        # Buy YES at 0.50, NO at 0.45
        # Combined cost = 0.95, guaranteed payout = 1.0
        # Locked edge = 0.05 per share
        pos.add_fill(side="YES", qty=100, cost=50)  # $0.50 per share
        pos.add_fill(side="NO", qty=100, cost=45)   # $0.45 per share
        
        assert pos.is_hedged
        assert pos.hedge_locked_value == 100  # 100 shares * $1
        assert abs(pos.hedge_locked_edge - 5.0) < 0.01  # $5 locked profit
    
    def test_unhedged_quantity(self):
        """Test unhedged quantity calculation."""
        pos = SimulatedPosition(market_id="test", venue="KALSHI")
        
        pos.add_fill(side="YES", qty=150, cost=75)
        pos.add_fill(side="NO", qty=100, cost=45)
        
        assert pos.unhedged_yes_qty == 50  # 150 - 100
        assert pos.unhedged_no_qty == 0
    
    def test_settle_yes_wins(self):
        """Test settlement when YES wins."""
        pos = SimulatedPosition(market_id="test", venue="KALSHI")
        
        pos.add_fill(side="YES", qty=100, cost=50)  # Paid $50
        pos.add_fill(side="NO", qty=50, cost=25)    # Paid $25
        
        pnl = pos.settle(outcome="YES")
        
        # YES wins: 100 shares * $1 = $100 payout
        # Total cost: $75
        # PnL = $100 - $75 = $25
        assert pnl == 25.0
        assert pos.realized_pnl == 25.0
    
    def test_settle_no_wins(self):
        """Test settlement when NO wins."""
        pos = SimulatedPosition(market_id="test", venue="KALSHI")
        
        pos.add_fill(side="YES", qty=100, cost=50)
        pos.add_fill(side="NO", qty=50, cost=25)
        
        pnl = pos.settle(outcome="NO")
        
        # NO wins: 50 shares * $1 = $50 payout
        # Total cost: $75
        # PnL = $50 - $75 = -$25
        assert pnl == -25.0


class TestPositionLedger:
    """Test position ledger."""
    
    def test_get_or_create(self):
        """Test getting or creating positions."""
        ledger = PositionLedger(venue="KALSHI")
        
        pos1 = ledger.get_or_create("market_1")
        pos2 = ledger.get_or_create("market_1")
        pos3 = ledger.get_or_create("market_2")
        
        assert pos1 is pos2  # Same instance
        assert pos1 is not pos3  # Different instance
    
    def test_add_fill_updates_position(self):
        """Test adding fills through ledger."""
        ledger = PositionLedger(venue="KALSHI")
        
        pos = ledger.add_fill("market_1", "YES", 100, 50)
        
        assert pos.yes_qty == 100
        assert len(ledger.open_positions) == 1
    
    def test_settle_market(self):
        """Test settling a market."""
        ledger = PositionLedger(venue="KALSHI")
        
        ledger.add_fill("market_1", "YES", 100, 50)
        ledger.add_fill("market_1", "NO", 100, 45)
        
        pnl, pos = ledger.settle_market("market_1", "YES")
        
        assert pnl == 5.0  # Locked edge
        assert ledger.total_realized_pnl == 5.0
        assert len(ledger.open_positions) == 0
    
    def test_summary(self):
        """Test ledger summary."""
        ledger = PositionLedger(venue="KALSHI")
        
        ledger.add_fill("market_1", "YES", 100, 50)
        ledger.add_fill("market_1", "NO", 100, 45)
        ledger.add_fill("market_2", "YES", 50, 30)
        
        summary = ledger.get_summary()
        
        assert summary["venue"] == "KALSHI"
        assert summary["total_positions"] == 2
        assert summary["open_positions"] == 2
        assert summary["total_yes_qty"] == 150
        assert summary["total_no_qty"] == 100
        assert summary["total_locked_edge"] == 5.0  # Only market_1 is hedged

