"""Tests for CopySignal generation and handling."""

import pytest
from datetime import datetime

from src.gabagool_mirror.core.signal import (
    CopySignal, SignalAction, SignalSide
)


class TestSignalIdGeneration:
    """Test deterministic signal_id generation."""
    
    def test_deterministic_id(self):
        """Signal ID should be deterministic for same inputs."""
        id1 = CopySignal.generate_signal_id("trade_123", 0, "0xabc")
        id2 = CopySignal.generate_signal_id("trade_123", 0, "0xabc")
        
        assert id1 == id2
        assert len(id1) == 32  # SHA256 truncated to 32 chars
    
    def test_different_trade_id_different_signal(self):
        """Different trade IDs should produce different signal IDs."""
        id1 = CopySignal.generate_signal_id("trade_123", 0)
        id2 = CopySignal.generate_signal_id("trade_456", 0)
        
        assert id1 != id2
    
    def test_different_fill_index_different_signal(self):
        """Different fill indices should produce different signal IDs."""
        id1 = CopySignal.generate_signal_id("trade_123", 0)
        id2 = CopySignal.generate_signal_id("trade_123", 1)
        
        assert id1 != id2
    
    def test_tx_hash_affects_signal_id(self):
        """Transaction hash should affect signal ID."""
        id1 = CopySignal.generate_signal_id("trade_123", 0, "0xabc")
        id2 = CopySignal.generate_signal_id("trade_123", 0, "0xdef")
        
        assert id1 != id2


class TestSignalFromPolymarketTrade:
    """Test CopySignal creation from Polymarket trade data."""
    
    def test_basic_trade_parsing(self):
        """Test parsing a basic trade."""
        trade = {
            "id": "trade_123",
            "timestamp": 1704672000000,  # ms timestamp
            "conditionId": "condition_abc",
            "title": "Bitcoin Up or Down - January 7",
            "outcome": "UP",
            "side": "BUY",
            "size": 100,
            "price": 0.55,
            "transactionHash": "0xabc123"
        }
        
        signal = CopySignal.from_polymarket_trade(trade)
        
        assert signal.signal_id is not None
        assert signal.ts_ms == 1704672000000
        assert signal.polymarket_market_id == "condition_abc"
        assert signal.side == SignalSide.YES
        assert signal.action == SignalAction.BUY
        assert signal.qty == 100
        assert signal.price == 0.55
        assert abs(signal.value_usd - 55.0) < 0.01
    
    def test_sell_action(self):
        """Test parsing a sell trade."""
        trade = {
            "id": "trade_456",
            "timestamp": 1704672000,  # seconds timestamp
            "conditionId": "condition_xyz",
            "outcome": "DOWN",
            "side": "SELL",
            "size": 50,
            "price": 0.40,
        }
        
        signal = CopySignal.from_polymarket_trade(trade)
        
        assert signal.side == SignalSide.NO
        assert signal.action == SignalAction.SELL
    
    def test_no_outcome_defaults_to_yes(self):
        """Test that missing outcome defaults to YES."""
        trade = {
            "id": "trade_789",
            "timestamp": 1704672000000,
            "size": 100,
            "price": 0.50,
        }
        
        signal = CopySignal.from_polymarket_trade(trade)
        
        assert signal.side == SignalSide.YES


class TestSignalSerialization:
    """Test signal serialization and deserialization."""
    
    def test_to_dict_and_back(self):
        """Test round-trip serialization."""
        original = CopySignal(
            signal_id="test_123",
            ts_ms=1704672000000,
            source="gabagool22",
            polymarket_market_id="market_abc",
            polymarket_event_name="Test Event",
            side=SignalSide.YES,
            action=SignalAction.BUY,
            qty=100,
            price=0.55,
            meta={"tx_hash": "0xabc"}
        )
        
        data = original.to_dict()
        restored = CopySignal.from_dict(data)
        
        assert restored.signal_id == original.signal_id
        assert restored.ts_ms == original.ts_ms
        assert restored.side == original.side
        assert restored.action == original.action
        assert restored.qty == original.qty
        assert restored.price == original.price
    
    def test_hash_and_equality(self):
        """Test signal hashing and equality."""
        signal1 = CopySignal(signal_id="test_123", ts_ms=0)
        signal2 = CopySignal(signal_id="test_123", ts_ms=1000)  # Different ts
        signal3 = CopySignal(signal_id="test_456", ts_ms=0)
        
        # Same signal_id = equal
        assert signal1 == signal2
        assert hash(signal1) == hash(signal2)
        
        # Different signal_id = not equal
        assert signal1 != signal3

