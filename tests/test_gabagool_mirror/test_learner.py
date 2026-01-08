"""Tests for online learner."""

import pytest
from datetime import datetime

from src.gabagool_mirror.learning.learner import (
    OnlineLearner, LearnerConfig, TradeOutcome
)


class TestLearnerBounds:
    """Test learner safety bounds enforcement."""
    
    def test_get_action_within_bounds(self):
        """Test that actions are always within bounds."""
        config = LearnerConfig(
            min_mapping_confidence_bounds=(0.5, 0.9),
            slippage_bps_buffer_bounds=(20, 150),
            max_qty_scale_bounds=(0.2, 0.8)
        )
        learner = OnlineLearner(config)
        
        for _ in range(100):
            confidence, slippage, scale = learner.get_action(
                spread_bps=50,
                depth=500,
                volatility=0.02,
                time_to_expiry_minutes=10,
                recent_fill_rate=0.8,
                recent_slippage_bps=30
            )
            
            assert 0.5 <= confidence <= 0.9
            assert 20 <= slippage <= 150
            assert 0.2 <= scale <= 0.8
    
    def test_exploration_rate(self):
        """Test exploration rate is approximately correct."""
        config = LearnerConfig(epsilon=0.3)  # 30% exploration
        learner = OnlineLearner(config)
        
        # Run many actions
        for _ in range(1000):
            learner.get_action(50, 500, 0.02, 10, 0.8, 30)
        
        # Check exploration rate
        total = learner.explorations + learner.exploitations
        actual_rate = learner.explorations / total
        
        assert 0.25 < actual_rate < 0.35  # Allow some variance


class TestCircuitBreaker:
    """Test circuit breaker functionality."""
    
    def test_consecutive_losses_triggers_breaker(self):
        """Test circuit breaker triggers on consecutive losses."""
        config = LearnerConfig(max_consecutive_losses=3)
        learner = OnlineLearner(config)
        
        assert not learner.circuit_breaker_active
        
        # Record 3 consecutive losses
        for i in range(3):
            learner.record_outcome(TradeOutcome(
                timestamp=datetime.utcnow(),
                spread_bps=50,
                depth=500,
                volatility=0.02,
                time_to_expiry_minutes=10,
                recent_fill_rate=0.8,
                recent_slippage_bps=30,
                mapping_confidence=0.7,
                slippage_buffer_bps=50,
                qty_scale=0.5,
                filled=True,
                slippage_realized_bps=30,
                pnl=-10.0  # Loss
            ))
        
        assert learner.circuit_breaker_active
        assert learner.consecutive_losses == 3
    
    def test_win_resets_consecutive_losses(self):
        """Test that a win resets consecutive loss counter."""
        config = LearnerConfig(max_consecutive_losses=5)
        learner = OnlineLearner(config)
        
        # 2 losses
        for _ in range(2):
            learner.record_outcome(TradeOutcome(
                timestamp=datetime.utcnow(),
                spread_bps=50, depth=500, volatility=0.02,
                time_to_expiry_minutes=10, recent_fill_rate=0.8,
                recent_slippage_bps=30, mapping_confidence=0.7,
                slippage_buffer_bps=50, qty_scale=0.5,
                filled=True, slippage_realized_bps=30,
                pnl=-10.0
            ))
        
        assert learner.consecutive_losses == 2
        
        # 1 win
        learner.record_outcome(TradeOutcome(
            timestamp=datetime.utcnow(),
            spread_bps=50, depth=500, volatility=0.02,
            time_to_expiry_minutes=10, recent_fill_rate=0.8,
            recent_slippage_bps=30, mapping_confidence=0.7,
            slippage_buffer_bps=50, qty_scale=0.5,
            filled=True, slippage_realized_bps=30,
            pnl=10.0  # Win
        ))
        
        assert learner.consecutive_losses == 0
    
    def test_drawdown_triggers_breaker(self):
        """Test circuit breaker triggers on drawdown."""
        config = LearnerConfig(max_drawdown_pct=0.10)  # 10% max drawdown
        learner = OnlineLearner(config)
        
        # Gain $100
        learner.record_outcome(TradeOutcome(
            timestamp=datetime.utcnow(),
            spread_bps=50, depth=500, volatility=0.02,
            time_to_expiry_minutes=10, recent_fill_rate=0.8,
            recent_slippage_bps=30, mapping_confidence=0.7,
            slippage_buffer_bps=50, qty_scale=0.5,
            filled=True, slippage_realized_bps=30,
            pnl=100.0
        ))
        
        assert learner.peak_pnl == 100.0
        
        # Lose $15 (15% drawdown > 10% limit)
        learner.record_outcome(TradeOutcome(
            timestamp=datetime.utcnow(),
            spread_bps=50, depth=500, volatility=0.02,
            time_to_expiry_minutes=10, recent_fill_rate=0.8,
            recent_slippage_bps=30, mapping_confidence=0.7,
            slippage_buffer_bps=50, qty_scale=0.5,
            filled=True, slippage_realized_bps=30,
            pnl=-15.0
        ))
        
        assert learner.circuit_breaker_active
    
    def test_circuit_breaker_returns_defaults(self):
        """Test circuit breaker returns conservative defaults."""
        config = LearnerConfig(max_consecutive_losses=1)
        learner = OnlineLearner(config)
        
        # Trigger breaker
        learner.record_outcome(TradeOutcome(
            timestamp=datetime.utcnow(),
            spread_bps=50, depth=500, volatility=0.02,
            time_to_expiry_minutes=10, recent_fill_rate=0.8,
            recent_slippage_bps=30, mapping_confidence=0.7,
            slippage_buffer_bps=50, qty_scale=0.5,
            filled=True, slippage_realized_bps=30,
            pnl=-10.0
        ))
        
        assert learner.circuit_breaker_active
        
        # Actions should return defaults
        confidence, slippage, scale = learner.get_action(
            50, 500, 0.02, 10, 0.8, 30
        )
        
        assert confidence == learner.default_min_mapping_confidence
        assert slippage == learner.default_slippage_bps_buffer
        assert scale == learner.default_max_qty_scale
    
    def test_reset_circuit_breaker(self):
        """Test manual circuit breaker reset."""
        config = LearnerConfig(max_consecutive_losses=1)
        learner = OnlineLearner(config)
        
        # Trigger breaker
        learner.record_outcome(TradeOutcome(
            timestamp=datetime.utcnow(),
            spread_bps=50, depth=500, volatility=0.02,
            time_to_expiry_minutes=10, recent_fill_rate=0.8,
            recent_slippage_bps=30, mapping_confidence=0.7,
            slippage_buffer_bps=50, qty_scale=0.5,
            filled=True, slippage_realized_bps=30,
            pnl=-10.0
        ))
        
        assert learner.circuit_breaker_active
        
        learner.reset_circuit_breaker()
        
        assert not learner.circuit_breaker_active
        assert learner.consecutive_losses == 0


class TestLearnerStats:
    """Test learner statistics."""
    
    def test_stats_accumulation(self):
        """Test stats accumulate correctly."""
        # Use high thresholds to avoid circuit breaker triggering
        config = LearnerConfig(
            max_consecutive_losses=10,
            max_drawdown_pct=0.9
        )
        learner = OnlineLearner(config)
        
        # Record some outcomes
        outcomes = [
            (True, 20, 10.0),   # Filled, 20bps slip, $10 profit -> total=10, peak=10
            (True, 30, -5.0),  # Filled, 30bps slip, $5 loss -> total=5, peak=10
            (False, 0, 0.0),   # Missed -> total=5, peak=10
            (True, 15, 15.0),  # Filled, 15bps slip, $15 profit -> total=20, peak=20
        ]
        
        for filled, slip, pnl in outcomes:
            learner.record_outcome(TradeOutcome(
                timestamp=datetime.utcnow(),
                spread_bps=50, depth=500, volatility=0.02,
                time_to_expiry_minutes=10, recent_fill_rate=0.8,
                recent_slippage_bps=30, mapping_confidence=0.7,
                slippage_buffer_bps=50, qty_scale=0.5,
                filled=filled, slippage_realized_bps=slip,
                pnl=pnl
            ))
        
        stats = learner.get_stats()
        
        assert stats["total_outcomes"] == 4
        assert stats["total_pnl"] == 20.0  # 10 - 5 + 0 + 15
        assert stats["peak_pnl"] == 20.0  # Peak is max(running total)

