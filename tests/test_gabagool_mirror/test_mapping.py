"""Tests for market mapping."""

import pytest
from datetime import datetime

from src.gabagool_mirror.core.mapping import (
    MarketMapping, MarketFeatures, MappingResult,
    Underlying, ContractType
)


class TestPolymarketFeatureExtraction:
    """Test Polymarket market feature extraction."""
    
    def test_btc_up_down_extraction(self):
        """Test extracting features from BTC up/down market."""
        mapper = MarketMapping()
        title = "Bitcoin Up or Down - January 7, 6:45PM-7:00PM ET"
        
        features = mapper.extract_polymarket_features(title)
        
        assert features.underlying == Underlying.BTC
        assert features.contract_type == ContractType.UP_DOWN_15M
        assert features.window_minutes == 15
    
    def test_eth_market_extraction(self):
        """Test extracting features from ETH market."""
        mapper = MarketMapping()
        title = "Ethereum Up or Down - January 7, 7:00PM-7:15PM ET"
        
        features = mapper.extract_polymarket_features(title)
        
        assert features.underlying == Underlying.ETH
        assert features.contract_type == ContractType.UP_DOWN_15M
    
    def test_single_time_format(self):
        """Test extracting time from single-time format."""
        mapper = MarketMapping()
        title = "Bitcoin Up or Down - January 7, 4PM ET"
        
        features = mapper.extract_polymarket_features(title)
        
        assert features.underlying == Underlying.BTC
        assert features.window_minutes == 15  # Default


class TestKalshiFeatureExtraction:
    """Test Kalshi market feature extraction."""
    
    def test_btc_15m_ticker_parsing(self):
        """Test parsing BTC 15-minute ticker."""
        mapper = MarketMapping()
        market = {
            "ticker": "KXBTC15M-26JAN071845-45",
            "title": "Bitcoin 15-min Up/Down",
            "floor_strike": 95000
        }
        
        features = mapper.extract_kalshi_features(market)
        
        assert features.underlying == Underlying.BTC
        assert features.contract_type == ContractType.UP_DOWN_15M
        assert features.window_minutes == 15
        assert features.strike == 95000
    
    def test_eth_ticker_parsing(self):
        """Test parsing ETH ticker."""
        mapper = MarketMapping()
        market = {
            "ticker": "KXETH15M-26JAN071900-00",
            "title": "Ethereum 15-min Up/Down"
        }
        
        features = mapper.extract_kalshi_features(market)
        
        assert features.underlying == Underlying.ETH


class TestMappingScoring:
    """Test mapping score calculation."""
    
    def test_perfect_match_score(self):
        """Test score for perfect matching markets."""
        mapper = MarketMapping()
        
        poly_features = MarketFeatures(
            underlying=Underlying.BTC,
            contract_type=ContractType.UP_DOWN_15M,
            expiry_ts=1704672000000,
            window_minutes=15
        )
        
        kalshi_features = MarketFeatures(
            underlying=Underlying.BTC,
            contract_type=ContractType.UP_DOWN_15M,
            expiry_ts=1704672000000,
            window_minutes=15
        )
        
        score, breakdown = mapper.score_mapping(poly_features, kalshi_features)
        
        assert score >= 0.95  # Near-perfect match
        assert breakdown["underlying"] == 1.0
        assert breakdown["time_proximity"] == 1.0
        assert breakdown["contract_type"] == 1.0
    
    def test_different_underlying_low_score(self):
        """Test low score for different underlyings."""
        mapper = MarketMapping()
        
        poly_features = MarketFeatures(underlying=Underlying.BTC)
        kalshi_features = MarketFeatures(underlying=Underlying.ETH)
        
        score, breakdown = mapper.score_mapping(poly_features, kalshi_features)
        
        assert breakdown["underlying"] == 0.0
        assert score < 0.5  # Should be low overall
    
    def test_time_proximity_decay(self):
        """Test time proximity score decay."""
        mapper = MarketMapping()
        
        # 15 minutes apart
        poly_features = MarketFeatures(
            underlying=Underlying.BTC,
            expiry_ts=1704672000000
        )
        
        kalshi_features = MarketFeatures(
            underlying=Underlying.BTC,
            expiry_ts=1704672000000 + (15 * 60 * 1000)  # 15 min later
        )
        
        score, breakdown = mapper.score_mapping(poly_features, kalshi_features)
        
        assert breakdown["time_proximity"] == 0.5  # Half of max time diff
    
    def test_time_too_far_zero_score(self):
        """Test zero time score when too far apart."""
        mapper = MarketMapping()
        
        # 1 hour apart
        poly_features = MarketFeatures(expiry_ts=1704672000000)
        kalshi_features = MarketFeatures(expiry_ts=1704672000000 + (60 * 60 * 1000))
        
        score, breakdown = mapper.score_mapping(poly_features, kalshi_features)
        
        assert breakdown["time_proximity"] == 0.0


class TestFindBestMatch:
    """Test finding best Kalshi match."""
    
    def test_finds_best_match(self):
        """Test finding best matching market."""
        mapper = MarketMapping()
        
        poly_title = "Bitcoin Up or Down - January 7, 6:45PM-7:00PM ET"
        poly_id = "poly_market_123"
        
        kalshi_markets = [
            {"ticker": "KXBTC15M-26JAN071845-45", "title": "BTC 15m", "floor_strike": 95000},
            {"ticker": "KXETH15M-26JAN071845-00", "title": "ETH 15m"},
            {"ticker": "KXBTC15M-26JAN072000-45", "title": "BTC 15m"},  # Later time
        ]
        
        result = mapper.find_best_kalshi_match(poly_title, poly_id, kalshi_markets)
        
        assert result.kalshi_ticker == "KXBTC15M-26JAN071845-45"  # Best time match
        assert result.confidence > 0.5
    
    def test_no_match_returns_low_confidence(self):
        """Test no match returns low confidence."""
        mapper = MarketMapping()
        
        poly_title = "Some Random Non-Crypto Market"
        poly_id = "poly_market_456"
        
        kalshi_markets = [
            {"ticker": "KXBTC15M-26JAN071845-45", "title": "BTC 15m"}
        ]
        
        result = mapper.find_best_kalshi_match(poly_title, poly_id, kalshi_markets)
        
        # Should have low confidence due to no underlying match
        assert result.confidence < 0.5

