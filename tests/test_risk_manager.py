"""Tests for risk manager."""

import pytest
from src.strategy.risk_manager import RiskManager, Trade


class TestRiskManager:
    """Test risk management functionality."""
    
    @pytest.fixture
    def risk_manager(self):
        """Create risk manager with test parameters."""
        return RiskManager(
            initial_bankroll_usd=200.0,
            max_risk_per_trade_usd=8.0,
            max_open_exposure_usd=24.0,
            daily_loss_limit_usd=20.0,
            consecutive_loss_limit=4
        )
    
    def test_initial_state(self, risk_manager):
        """Test initial state."""
        assert risk_manager.current_bankroll == 200.0
        assert risk_manager.peak_bankroll == 200.0
        assert len(risk_manager.trades) == 0
        assert not risk_manager.is_halted
    
    def test_position_sizing(self, risk_manager):
        """Test position sizing calculation."""
        # High edge should give larger size
        size_high = risk_manager.compute_position_size(edge=0.05, confidence=0.4)
        
        # Low edge should give smaller size
        size_low = risk_manager.compute_position_size(edge=0.02, confidence=0.4)
        
        assert size_high > size_low
        assert size_high <= 8.0  # Max risk per trade
    
    def test_available_risk_budget(self, risk_manager):
        """Test available risk budget."""
        available = risk_manager.get_available_risk_budget()
        
        assert available == 8.0  # Max per trade
        
        # Open a position
        trade = risk_manager.open_position(
            market_id="TEST-MARKET",
            side="YES",
            size_usd=8.0,
            entry_price=0.5
        )
        
        assert trade is not None
        
        # Available should be reduced
        available_after = risk_manager.get_available_risk_budget()
        assert available_after < available
    
    def test_circuit_breaker_daily_loss(self, risk_manager):
        """Test daily loss limit circuit breaker."""
        # Simulate losing trades
        for i in range(3):
            trade = risk_manager.open_position(
                market_id=f"MARKET-{i}",
                side="YES",
                size_usd=8.0,
                entry_price=0.7
            )
            
            # Close at loss
            risk_manager.close_position(trade, exit_price=0.0)
        
        # Should be halted due to daily loss
        assert risk_manager.is_halted
    
    def test_circuit_breaker_consecutive_losses(self, risk_manager):
        """Test consecutive loss circuit breaker."""
        # Simulate consecutive losing trades
        for i in range(4):
            trade = risk_manager.open_position(
                market_id=f"MARKET-{i}",
                side="YES",
                size_usd=5.0,
                entry_price=0.5
            )
            
            # Close at small loss
            risk_manager.close_position(trade, exit_price=0.0)
        
        # Should be in cooldown
        assert risk_manager.cooldown_until is not None
    
    def test_position_open_and_close(self, risk_manager):
        """Test opening and closing positions."""
        initial_bankroll = risk_manager.current_bankroll
        
        # Open position
        trade = risk_manager.open_position(
            market_id="TEST-MARKET",
            side="YES",
            size_usd=8.0,
            entry_price=0.4
        )
        
        assert trade is not None
        assert len(risk_manager.open_trades) == 1
        
        # Close at profit
        risk_manager.close_position(trade, exit_price=1.0)
        
        assert len(risk_manager.open_trades) == 0
        assert trade.pnl is not None
        assert trade.pnl > 0
        assert risk_manager.current_bankroll > initial_bankroll
    
    def test_metrics(self, risk_manager):
        """Test metrics calculation."""
        # Open and close some trades
        for i in range(3):
            trade = risk_manager.open_position(
                market_id=f"MARKET-{i}",
                side="YES",
                size_usd=5.0,
                entry_price=0.5
            )
            
            # Alternate wins and losses
            exit_price = 1.0 if i % 2 == 0 else 0.0
            risk_manager.close_position(trade, exit_price)
        
        metrics = risk_manager.get_metrics()
        
        assert metrics["num_trades"] == 3
        assert 0 <= metrics["win_rate"] <= 1
        assert "total_pnl" in metrics


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

