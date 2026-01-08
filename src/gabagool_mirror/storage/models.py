"""
SQLAlchemy async models for Gabagool Mirror Bot.

All core entities are persisted for:
- Audit trail
- Replay capability  
- Performance analysis
- Learning
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, 
    Text, JSON, ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Run(Base):
    """
    Execution run metadata.
    
    Each bot invocation creates a new run for tracking.
    """
    __tablename__ = "runs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), unique=True, nullable=False, index=True)
    mode = Column(String(16), nullable=False)  # SIM, SHADOW, LIVE
    start_ts = Column(DateTime, default=datetime.utcnow)
    end_ts = Column(DateTime, nullable=True)
    git_sha = Column(String(40), nullable=True)
    config_hash = Column(String(64), nullable=True)
    config_json = Column(JSON, nullable=True)
    status = Column(String(16), default="running")  # running, completed, failed
    
    # Relationships
    signals = relationship("Signal", back_populates="run")


class Signal(Base):
    """
    Canonical CopySignal from gabagool trades.
    
    Unique constraint on signal_id ensures idempotent processing.
    """
    __tablename__ = "signals"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_id = Column(String(64), unique=True, nullable=False, index=True)
    run_id = Column(String(64), ForeignKey("runs.run_id"), nullable=True)
    
    ts_ms = Column(Integer, nullable=False, index=True)
    source = Column(String(64), default="gabagool22")
    
    # Polymarket info
    polymarket_market_id = Column(String(128), index=True)
    polymarket_event_name = Column(Text)
    polymarket_slug = Column(String(256))
    
    # Trade details
    side = Column(String(8))  # YES, NO
    action = Column(String(8))  # BUY, SELL
    qty = Column(Float)
    price = Column(Float)
    value_usd = Column(Float)
    
    # Metadata
    meta_json = Column(JSON, nullable=True)
    
    # Processing state
    processed = Column(Boolean, default=False)
    processed_at = Column(DateTime, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    run = relationship("Run", back_populates="signals")
    mapping = relationship("Mapping", back_populates="signal", uselist=False)
    polymarket_orders = relationship(
        "SimOrder",
        back_populates="signal",
        foreign_keys="SimOrder.signal_id",
        primaryjoin="Signal.signal_id == SimOrder.signal_id"
    )
    
    __table_args__ = (
        Index("ix_signals_ts_source", "ts_ms", "source"),
    )


class Mapping(Base):
    """
    Polymarket to Kalshi market mapping result.
    """
    __tablename__ = "mappings"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_id = Column(String(64), ForeignKey("signals.signal_id"), unique=True)
    
    polymarket_market_id = Column(String(128), index=True)
    kalshi_market_id = Column(String(128), nullable=True, index=True)
    kalshi_ticker = Column(String(64), nullable=True)
    
    confidence = Column(Float, default=0.0)
    reason = Column(Text, nullable=True)
    feature_breakdown_json = Column(JSON, nullable=True)
    
    # Extracted features
    polymarket_features_json = Column(JSON, nullable=True)
    kalshi_features_json = Column(JSON, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    signal = relationship("Signal", back_populates="mapping")


class SimOrder(Base):
    """
    Simulated order (for both Polymarket-exact and Kalshi sims).
    """
    __tablename__ = "sim_orders"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(64), unique=True, nullable=False, index=True)
    signal_id = Column(String(64), ForeignKey("signals.signal_id"), index=True)
    
    venue = Column(String(16))  # POLYMARKET, KALSHI
    market_id = Column(String(128), index=True)
    ticker = Column(String(64), nullable=True)
    
    side = Column(String(8))  # YES, NO
    action = Column(String(8))  # BUY, SELL
    price = Column(Float)  # Limit price
    qty = Column(Float)
    
    # Simulation parameters
    latency_ms = Column(Integer, default=0)
    slippage_bps = Column(Integer, default=0)
    
    # Status
    status = Column(String(16), default="pending")  # pending, filled, partial, missed, cancelled
    filled_qty = Column(Float, default=0.0)
    filled_avg_price = Column(Float, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    filled_at = Column(DateTime, nullable=True)
    
    # Relationships
    signal = relationship("Signal", back_populates="polymarket_orders", foreign_keys=[signal_id])
    fills = relationship("SimFill", back_populates="order")


class SimFill(Base):
    """
    Simulated fill for an order.
    """
    __tablename__ = "sim_fills"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    fill_id = Column(String(64), unique=True, nullable=False)
    order_id = Column(String(64), ForeignKey("sim_orders.order_id"), index=True)
    
    price = Column(Float)
    qty = Column(Float)
    fee = Column(Float, default=0.0)
    
    # For Kalshi sim: orderbook level filled against
    book_level = Column(Integer, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    order = relationship("SimOrder", back_populates="fills")


class SimPosition(Base):
    """
    Simulated position ledger.
    
    Tracks average cost and quantities for each side.
    """
    __tablename__ = "sim_positions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    position_id = Column(String(64), unique=True, nullable=False, index=True)
    
    venue = Column(String(16))  # POLYMARKET, KALSHI
    market_id = Column(String(128), index=True)
    
    # YES side
    yes_qty = Column(Float, default=0.0)
    yes_avg_cost = Column(Float, default=0.0)
    yes_total_cost = Column(Float, default=0.0)
    
    # NO side
    no_qty = Column(Float, default=0.0)
    no_avg_cost = Column(Float, default=0.0)
    no_total_cost = Column(Float, default=0.0)
    
    # PnL
    realized_pnl = Column(Float, default=0.0)
    unrealized_pnl = Column(Float, default=0.0)
    
    # Status
    status = Column(String(16), default="open")  # open, closed, settled
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    settled_at = Column(DateTime, nullable=True)
    
    __table_args__ = (
        UniqueConstraint("venue", "market_id", name="uq_position_venue_market"),
    )


class Outcome(Base):
    """
    Market resolution outcome.
    """
    __tablename__ = "outcomes"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    market_id = Column(String(128), unique=True, nullable=False, index=True)
    venue = Column(String(16))  # POLYMARKET, KALSHI
    
    resolved_ts = Column(DateTime, nullable=True)
    outcome = Column(String(8), nullable=True)  # YES, NO, null if unresolved
    payout_per_share = Column(Float, default=1.0)
    
    # Raw resolution data
    resolution_json = Column(JSON, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)


class Metric(Base):
    """
    Time-series metrics for monitoring and analysis.
    """
    __tablename__ = "metrics"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(DateTime, default=datetime.utcnow, index=True)
    name = Column(String(64), index=True)
    value = Column(Float)
    labels_json = Column(JSON, nullable=True)
    
    __table_args__ = (
        Index("ix_metrics_name_ts", "name", "ts"),
    )


class Cursor(Base):
    """
    Persistent cursor for tracking ingestion progress.
    """
    __tablename__ = "cursors"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), unique=True, nullable=False)
    value = Column(Integer, default=0)  # Typically timestamp in ms
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

