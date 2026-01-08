"""Tests for settlement engine."""

import time
import pytest
from src.data.brti_feed import BRTIFeed, PriceTick
from src.models.settlement_engine import SettlementEngine


class TestSettlementEngine:
    """Test settlement engine functionality."""
    
    @pytest.fixture
    def mock_brti_feed(self):
        """Create mock BRTI feed with test data."""
        feed = BRTIFeed(
            use_cf_benchmarks=False,
            fallback_exchanges=["coinbase"],
            update_interval=1.0,
            buffer_size=300
        )
        
        # Add mock price data
        current_time = time.time()
        for i in range(120):
            tick = PriceTick(
                timestamp=current_time - 120 + i,
                price=50000 + i * 10,  # Linearly increasing price
                source="test"
            )
            feed.price_buffer.append(tick)
        
        return feed
    
    def test_avg60_computation_convention_a(self, mock_brti_feed):
        """Test avg60 computation with convention A."""
        engine = SettlementEngine(
            brti_feed=mock_brti_feed,
            convention="A"
        )
        
        settle_time = time.time()
        avg60 = engine.compute_avg60_for_timestamp(settle_time, convention="A")
        
        assert avg60 is not None
        assert isinstance(avg60, float)
        assert avg60 > 0
    
    def test_avg60_computation_convention_b(self, mock_brti_feed):
        """Test avg60 computation with convention B."""
        engine = SettlementEngine(
            brti_feed=mock_brti_feed,
            convention="B"
        )
        
        settle_time = time.time()
        avg60 = engine.compute_avg60_for_timestamp(settle_time, convention="B")
        
        assert avg60 is not None
        assert isinstance(avg60, float)
        assert avg60 > 0
    
    def test_distance_to_threshold(self, mock_brti_feed):
        """Test distance to threshold calculation."""
        engine = SettlementEngine(
            brti_feed=mock_brti_feed,
            convention="A"
        )
        
        engine.update()
        
        baseline = 50000
        distance = engine.compute_distance_to_threshold(baseline)
        
        assert distance is not None
        assert isinstance(distance, float)
    
    def test_outcome_locked(self, mock_brti_feed):
        """Test outcome lock detection."""
        engine = SettlementEngine(
            brti_feed=mock_brti_feed,
            convention="A"
        )
        
        engine.update()
        
        baseline = 40000  # Well below current price
        locked = engine.is_outcome_locked(
            baseline=baseline,
            seconds_remaining=5,
            volatility_per_second=0.0001
        )
        
        # With very low volatility and 5 seconds remaining,
        # outcome should be locked to YES
        assert locked == "YES"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

