"""
Repository pattern for database operations.

Provides a clean interface for all database CRUD operations
with proper transaction handling.
"""

import hashlib
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import asdict
import logging

from sqlalchemy import select, update, delete, and_, or_, func
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .database import Database, get_database
from .models import (
    Run, Signal, Mapping, SimOrder, SimFill, 
    SimPosition, Outcome, Metric, Cursor
)
from ..core.signal import CopySignal
from ..core.mapping import MappingResult

logger = logging.getLogger(__name__)


class Repository:
    """
    Database repository for all entities.
    
    Provides transactional operations with proper error handling.
    """
    
    def __init__(self, database: Optional[Database] = None):
        """
        Initialize repository.
        
        Args:
            database: Database instance. Uses global if None.
        """
        self._db = database or get_database()
    
    # === Run Management ===
    
    async def create_run(
        self,
        mode: str,
        git_sha: Optional[str] = None,
        config: Optional[Dict] = None
    ) -> str:
        """Create a new execution run."""
        run_id = str(uuid.uuid4())[:16]
        config_hash = hashlib.sha256(str(config).encode()).hexdigest()[:16] if config else None
        
        async with self._db.session() as session:
            run = Run(
                run_id=run_id,
                mode=mode,
                git_sha=git_sha,
                config_hash=config_hash,
                config_json=config
            )
            session.add(run)
        
        logger.info(f"Created run {run_id} in mode {mode}")
        return run_id
    
    async def complete_run(self, run_id: str, status: str = "completed") -> None:
        """Mark a run as completed."""
        async with self._db.session() as session:
            await session.execute(
                update(Run)
                .where(Run.run_id == run_id)
                .values(end_ts=datetime.utcnow(), status=status)
            )
    
    # === Signal Management ===
    
    async def save_signal(self, signal: CopySignal, run_id: Optional[str] = None) -> None:
        """
        Save a CopySignal to database.
        
        Uses upsert to handle duplicates gracefully.
        """
        async with self._db.session() as session:
            # Check for SQLite vs Postgres for upsert syntax
            db_url = str(self._db.engine.url)
            
            values = {
                "signal_id": signal.signal_id,
                "run_id": run_id,
                "ts_ms": signal.ts_ms,
                "source": signal.source,
                "polymarket_market_id": signal.polymarket_market_id,
                "polymarket_event_name": signal.polymarket_event_name,
                "polymarket_slug": signal.polymarket_slug,
                "side": signal.side.value,
                "action": signal.action.value,
                "qty": signal.qty,
                "price": signal.price,
                "value_usd": signal.value_usd,
                "meta_json": signal.meta,
                "processed": signal.processed,
                "created_at": signal.created_at or datetime.utcnow()
            }
            
            if "sqlite" in db_url:
                stmt = sqlite_insert(Signal).values(**values)
                stmt = stmt.on_conflict_do_nothing(index_elements=["signal_id"])
            else:
                stmt = pg_insert(Signal).values(**values)
                stmt = stmt.on_conflict_do_nothing(index_elements=["signal_id"])
            
            await session.execute(stmt)
    
    async def get_signal(self, signal_id: str) -> Optional[Signal]:
        """Get a signal by ID."""
        async with self._db.session() as session:
            result = await session.execute(
                select(Signal).where(Signal.signal_id == signal_id)
            )
            return result.scalar_one_or_none()
    
    async def get_signals_since(self, ts_ms: int, limit: int = 1000) -> List[Signal]:
        """Get signals since a timestamp."""
        async with self._db.session() as session:
            result = await session.execute(
                select(Signal)
                .where(Signal.ts_ms >= ts_ms)
                .order_by(Signal.ts_ms)
                .limit(limit)
            )
            return list(result.scalars().all())
    
    async def get_recent_signal_ids(self, limit: int = 10000) -> List[str]:
        """Get recent signal IDs for deduplication."""
        async with self._db.session() as session:
            result = await session.execute(
                select(Signal.signal_id)
                .order_by(Signal.ts_ms.desc())
                .limit(limit)
            )
            return [row[0] for row in result.all()]
    
    async def mark_signal_processed(self, signal_id: str) -> None:
        """Mark a signal as processed."""
        async with self._db.session() as session:
            await session.execute(
                update(Signal)
                .where(Signal.signal_id == signal_id)
                .values(processed=True, processed_at=datetime.utcnow())
            )
    
    # === Mapping Management ===
    
    async def save_mapping(self, signal_id: str, result: MappingResult) -> None:
        """Save a mapping result."""
        async with self._db.session() as session:
            mapping = Mapping(
                signal_id=signal_id,
                polymarket_market_id=result.polymarket_market_id,
                kalshi_market_id=result.kalshi_market_id,
                kalshi_ticker=result.kalshi_ticker,
                confidence=result.confidence,
                reason=result.reason,
                feature_breakdown_json=result.feature_breakdown,
                polymarket_features_json=asdict(result.polymarket_features) if result.polymarket_features else None,
                kalshi_features_json=asdict(result.kalshi_features) if result.kalshi_features else None
            )
            session.add(mapping)
    
    async def get_mapping(self, signal_id: str) -> Optional[Mapping]:
        """Get mapping for a signal."""
        async with self._db.session() as session:
            result = await session.execute(
                select(Mapping).where(Mapping.signal_id == signal_id)
            )
            return result.scalar_one_or_none()
    
    # === Order Management ===
    
    async def save_sim_order(
        self,
        order_id: str,
        signal_id: str,
        venue: str,
        market_id: str,
        side: str,
        action: str,
        price: float,
        qty: float,
        ticker: Optional[str] = None,
        latency_ms: int = 0,
        slippage_bps: int = 0
    ) -> None:
        """Save a simulated order."""
        async with self._db.session() as session:
            order = SimOrder(
                order_id=order_id,
                signal_id=signal_id,
                venue=venue,
                market_id=market_id,
                ticker=ticker,
                side=side,
                action=action,
                price=price,
                qty=qty,
                latency_ms=latency_ms,
                slippage_bps=slippage_bps
            )
            session.add(order)
    
    async def update_order_status(
        self,
        order_id: str,
        status: str,
        filled_qty: float = 0.0,
        filled_avg_price: Optional[float] = None
    ) -> None:
        """Update order status after simulation."""
        async with self._db.session() as session:
            values = {"status": status, "filled_qty": filled_qty}
            if filled_avg_price is not None:
                values["filled_avg_price"] = filled_avg_price
            if status in ("filled", "partial"):
                values["filled_at"] = datetime.utcnow()
            
            await session.execute(
                update(SimOrder)
                .where(SimOrder.order_id == order_id)
                .values(**values)
            )
    
    async def save_sim_fill(
        self,
        order_id: str,
        price: float,
        qty: float,
        fee: float = 0.0,
        book_level: Optional[int] = None
    ) -> str:
        """Save a simulated fill."""
        fill_id = f"{order_id}_{uuid.uuid4().hex[:8]}"
        
        async with self._db.session() as session:
            fill = SimFill(
                fill_id=fill_id,
                order_id=order_id,
                price=price,
                qty=qty,
                fee=fee,
                book_level=book_level
            )
            session.add(fill)
        
        return fill_id
    
    # === Position Management ===
    
    async def get_or_create_position(self, venue: str, market_id: str) -> SimPosition:
        """Get or create a position for a market."""
        position_id = f"{venue}_{market_id}"
        
        async with self._db.session() as session:
            result = await session.execute(
                select(SimPosition).where(SimPosition.position_id == position_id)
            )
            position = result.scalar_one_or_none()
            
            if not position:
                position = SimPosition(
                    position_id=position_id,
                    venue=venue,
                    market_id=market_id
                )
                session.add(position)
                await session.flush()
            
            return position
    
    async def update_position(
        self,
        venue: str,
        market_id: str,
        side: str,
        qty_delta: float,
        cost_delta: float,
        avg_price: float
    ) -> None:
        """Update position after a fill."""
        position_id = f"{venue}_{market_id}"
        
        async with self._db.session() as session:
            # Get current position
            result = await session.execute(
                select(SimPosition).where(SimPosition.position_id == position_id)
            )
            position = result.scalar_one_or_none()
            
            if not position:
                position = SimPosition(
                    position_id=position_id,
                    venue=venue,
                    market_id=market_id
                )
                session.add(position)
            
            # Update the appropriate side
            if side == "YES":
                new_qty = position.yes_qty + qty_delta
                new_total_cost = position.yes_total_cost + cost_delta
                position.yes_qty = new_qty
                position.yes_total_cost = new_total_cost
                position.yes_avg_cost = new_total_cost / new_qty if new_qty > 0 else 0
            else:
                new_qty = position.no_qty + qty_delta
                new_total_cost = position.no_total_cost + cost_delta
                position.no_qty = new_qty
                position.no_total_cost = new_total_cost
                position.no_avg_cost = new_total_cost / new_qty if new_qty > 0 else 0
    
    async def get_all_positions(self, venue: Optional[str] = None) -> List[SimPosition]:
        """Get all positions, optionally filtered by venue."""
        async with self._db.session() as session:
            query = select(SimPosition)
            if venue:
                query = query.where(SimPosition.venue == venue)
            result = await session.execute(query)
            return list(result.scalars().all())
    
    # === Outcome Management ===
    
    async def save_outcome(
        self,
        market_id: str,
        venue: str,
        outcome: str,
        resolved_ts: Optional[datetime] = None,
        payout_per_share: float = 1.0,
        resolution_json: Optional[Dict] = None
    ) -> None:
        """Save market resolution outcome."""
        async with self._db.session() as session:
            existing = await session.execute(
                select(Outcome).where(Outcome.market_id == market_id)
            )
            existing_outcome = existing.scalar_one_or_none()
            
            if existing_outcome:
                existing_outcome.outcome = outcome
                existing_outcome.resolved_ts = resolved_ts or datetime.utcnow()
                existing_outcome.payout_per_share = payout_per_share
                existing_outcome.resolution_json = resolution_json
            else:
                session.add(Outcome(
                    market_id=market_id,
                    venue=venue,
                    outcome=outcome,
                    resolved_ts=resolved_ts or datetime.utcnow(),
                    payout_per_share=payout_per_share,
                    resolution_json=resolution_json
                ))
    
    async def get_outcome(self, market_id: str) -> Optional[Outcome]:
        """Get outcome for a market."""
        async with self._db.session() as session:
            result = await session.execute(
                select(Outcome).where(Outcome.market_id == market_id)
            )
            return result.scalar_one_or_none()
    
    # === Metrics ===
    
    async def record_metric(
        self,
        name: str,
        value: float,
        labels: Optional[Dict[str, str]] = None
    ) -> None:
        """Record a metric."""
        async with self._db.session() as session:
            metric = Metric(
                name=name,
                value=value,
                labels_json=labels
            )
            session.add(metric)
    
    async def get_metrics(
        self,
        name: str,
        since: Optional[datetime] = None,
        limit: int = 1000
    ) -> List[Metric]:
        """Get metrics by name."""
        async with self._db.session() as session:
            query = select(Metric).where(Metric.name == name)
            if since:
                query = query.where(Metric.ts >= since)
            query = query.order_by(Metric.ts.desc()).limit(limit)
            result = await session.execute(query)
            return list(result.scalars().all())
    
    # === Cursor Management ===
    
    async def get_cursor(self, name: str) -> Optional[int]:
        """Get cursor value."""
        async with self._db.session() as session:
            result = await session.execute(
                select(Cursor.value).where(Cursor.name == name)
            )
            row = result.first()
            return row[0] if row else None
    
    async def update_cursor(self, name: str, value: int) -> None:
        """Update cursor value."""
        async with self._db.session() as session:
            existing = await session.execute(
                select(Cursor).where(Cursor.name == name)
            )
            cursor = existing.scalar_one_or_none()
            
            if cursor:
                cursor.value = value
            else:
                session.add(Cursor(name=name, value=value))
    
    # === Analytics ===
    
    async def get_simulation_summary(self, venue: str) -> Dict[str, Any]:
        """Get summary statistics for a simulation venue."""
        async with self._db.session() as session:
            # Get positions
            positions = await session.execute(
                select(SimPosition).where(SimPosition.venue == venue)
            )
            positions = list(positions.scalars().all())
            
            # Calculate totals
            total_yes_qty = sum(p.yes_qty for p in positions)
            total_no_qty = sum(p.no_qty for p in positions)
            total_yes_cost = sum(p.yes_total_cost for p in positions)
            total_no_cost = sum(p.no_total_cost for p in positions)
            total_realized_pnl = sum(p.realized_pnl for p in positions)
            
            # Get order stats
            orders = await session.execute(
                select(
                    SimOrder.status,
                    func.count(SimOrder.id),
                    func.sum(SimOrder.qty),
                    func.sum(SimOrder.filled_qty)
                )
                .where(SimOrder.venue == venue)
                .group_by(SimOrder.status)
            )
            
            order_stats = {}
            for row in orders.all():
                order_stats[row[0]] = {
                    "count": row[1],
                    "total_qty": row[2] or 0,
                    "filled_qty": row[3] or 0
                }
            
            return {
                "venue": venue,
                "positions": len(positions),
                "total_yes_qty": total_yes_qty,
                "total_no_qty": total_no_qty,
                "total_yes_cost": total_yes_cost,
                "total_no_cost": total_no_cost,
                "total_realized_pnl": total_realized_pnl,
                "order_stats": order_stats
            }

