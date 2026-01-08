"""
Main Engine - Orchestrates the Gabagool Mirror Bot.

Coordinates:
- Signal ingestion from Polymarket
- Dual simulation (Polymarket exact + Kalshi equivalent)
- Database persistence
- Metrics collection
- Graceful shutdown
"""

import asyncio
import signal
import logging
from datetime import datetime
from typing import List, Optional, Set
from contextlib import asynccontextmanager

from .config import get_settings, ExecutionMode
from .core.signal import CopySignal
from .core.dedup import SignalDeduplicator
from .adapters.polymarket_adapter import PolymarketAdapter
from .adapters.kalshi_adapter import KalshiAdapter
from .simulation.polymarket_sim import PolymarketSimulator
from .simulation.kalshi_sim import KalshiSimulator
from .learning.learner import OnlineLearner, TradeOutcome
from .storage.database import Database, get_database
from .storage.repository import Repository
from .ops.logger import setup_logging, get_json_logger
from .ops.metrics import get_metrics
from .ops.health import HealthServer

logger = logging.getLogger(__name__)


class GabagoolMirrorEngine:
    """
    Main engine for Gabagool Mirror Bot.
    
    Modes:
    - SIM: Replay stored signals (no external calls)
    - SHADOW: Real-time data, simulated execution
    - LIVE: Real execution on Kalshi (guarded)
    """
    
    def __init__(
        self,
        mode: Optional[ExecutionMode] = None,
        config_overrides: Optional[dict] = None
    ):
        """
        Initialize engine.
        
        Args:
            mode: Execution mode (default from settings)
            config_overrides: Override configuration values
        """
        settings = get_settings()
        self.mode = mode or settings.execution_mode
        
        # Apply overrides
        if config_overrides:
            for key, value in config_overrides.items():
                if hasattr(settings, key):
                    setattr(settings, key, value)
        
        # Core components
        self.database: Optional[Database] = None
        self.repository: Optional[Repository] = None
        
        # Adapters
        self.polymarket: Optional[PolymarketAdapter] = None
        self.kalshi: Optional[KalshiAdapter] = None
        
        # Simulations
        self.poly_sim: Optional[PolymarketSimulator] = None
        self.kalshi_sim: Optional[KalshiSimulator] = None
        
        # Deduplication
        self.deduplicator: Optional[SignalDeduplicator] = None
        
        # Learning
        self.learner: Optional[OnlineLearner] = None
        
        # Ops
        self.health_server: Optional[HealthServer] = None
        self.metrics = get_metrics()
        
        # State
        self._running = False
        self._shutdown_event = asyncio.Event()
        self._run_id: Optional[str] = None
        
        # Stats
        self._start_time: Optional[datetime] = None
        self._signals_processed = 0
    
    async def initialize(self) -> None:
        """Initialize all components."""
        settings = get_settings()
        
        logger.info(f"Initializing Gabagool Mirror Engine in {self.mode.value} mode")
        
        # Database
        self.database = get_database()
        await self.database.initialize()
        self.repository = Repository(self.database)
        
        # Create run record
        self._run_id = await self.repository.create_run(
            mode=self.mode.value,
            config=settings.model_dump() if hasattr(settings, 'model_dump') else {}
        )
        
        # Deduplicator
        self.deduplicator = SignalDeduplicator(self.repository)
        await self.deduplicator.initialize()
        
        # Adapters (only for SHADOW and LIVE modes)
        if self.mode in (ExecutionMode.SHADOW, ExecutionMode.LIVE):
            self.polymarket = PolymarketAdapter()
            await self.polymarket.connect()
            
            self.kalshi = KalshiAdapter()
            await self.kalshi.connect()
        
        # Simulators
        self.poly_sim = PolymarketSimulator(self.repository)
        self.kalshi_sim = KalshiSimulator(
            kalshi_adapter=self.kalshi,
            repository=self.repository,
            latency_ms=settings.default_latency_ms
        )
        
        # Learner
        if settings.learning_enabled:
            self.learner = OnlineLearner()
        
        # Health server
        self.health_server = HealthServer(
            port=settings.health_port,
            metrics_port=settings.metrics_port
        )
        
        # Register health checks
        self.health_server.register_health_check(
            "database",
            self._check_database_health
        )
        self.health_server.register_health_check(
            "polymarket",
            self._check_polymarket_health
        )
        self.health_server.register_health_check(
            "kalshi",
            self._check_kalshi_health
        )
        
        self.health_server.set_status_provider(self._get_status)
        
        await self.health_server.start()
        self.health_server.set_ready(True)
        
        self._start_time = datetime.utcnow()
        logger.info("Engine initialized successfully")
    
    async def shutdown(self) -> None:
        """Graceful shutdown."""
        logger.info("Shutting down engine...")
        self._running = False
        self._shutdown_event.set()
        
        # Complete run
        if self.repository and self._run_id:
            await self.repository.complete_run(self._run_id)
        
        # Stop health server
        if self.health_server:
            await self.health_server.stop()
        
        # Disconnect adapters
        if self.polymarket:
            await self.polymarket.disconnect()
        if self.kalshi:
            await self.kalshi.disconnect()
        
        # Close database
        if self.database:
            await self.database.close()
        
        logger.info("Engine shutdown complete")
    
    @asynccontextmanager
    async def running(self):
        """Context manager for running the engine."""
        await self.initialize()
        try:
            yield self
        finally:
            await self.shutdown()
    
    async def process_signal(self, signal: CopySignal) -> None:
        """
        Process a single CopySignal through both simulations.
        
        Args:
            signal: CopySignal to process
        """
        # Check deduplication
        if await self.deduplicator.is_duplicate(signal):
            logger.debug(f"Duplicate signal ignored: {signal.signal_id}")
            return
        
        # Save signal
        await self.repository.save_signal(signal, self._run_id)
        
        self.metrics.inc_signals_ingested()
        self._signals_processed += 1
        
        logger.info(
            f"Processing signal: {signal.action.value} {signal.side.value} "
            f"{signal.qty:.2f}@{signal.price:.3f} | {signal.polymarket_event_name[:40]}..."
        )
        
        # Run both simulations in parallel
        poly_task = asyncio.create_task(
            self.poly_sim.process_signal(signal)
        )
        kalshi_task = asyncio.create_task(
            self.kalshi_sim.process_signal(signal)
        )
        
        poly_pos, (kalshi_fill, kalshi_pos) = await asyncio.gather(
            poly_task,
            kalshi_task
        )
        
        # Update metrics
        if kalshi_fill:
            self.metrics.inc_signals_filled("KALSHI", kalshi_fill.status.value)
            if kalshi_fill.slippage_bps > 0:
                self.metrics.observe_slippage(kalshi_fill.slippage_bps)
            self.metrics.observe_latency(kalshi_fill.latency_ms)
        else:
            self.metrics.inc_missed_trades()
        
        # Mark processed
        await self.deduplicator.mark_processed(signal)
        
        # Live execution (if enabled)
        if self.mode == ExecutionMode.LIVE and kalshi_fill and kalshi_fill.is_complete:
            await self._execute_live(signal, kalshi_fill)
    
    async def _execute_live(self, signal: CopySignal, sim_fill) -> None:
        """
        Execute live trade on Kalshi.
        
        GUARDED: Only runs if KALSHI_LIVE_ENABLED=true
        """
        settings = get_settings()
        
        if not settings.kalshi_live_enabled:
            logger.warning(
                "LIVE execution skipped - KALSHI_LIVE_ENABLED=false"
            )
            return
        
        if not self.kalshi or not self.kalshi._authenticated:
            logger.error("Cannot execute live: Kalshi not authenticated")
            return
        
        # Get mapping
        mapping = await self.kalshi_sim.get_mapping(signal)
        if not mapping.kalshi_ticker:
            logger.error("Cannot execute live: no Kalshi ticker mapped")
            return
        
        # Place order
        logger.warning(
            f"LIVE ORDER: {signal.action.value} {signal.side.value} "
            f"{sim_fill.filled_qty:.0f} contracts on {mapping.kalshi_ticker}"
        )
        
        result = await self.kalshi.place_order(
            ticker=mapping.kalshi_ticker,
            side=signal.side.value.lower(),
            action=signal.action.value.lower(),
            count=int(sim_fill.filled_qty),
            price_cents=int(sim_fill.avg_fill_price * 100),
            order_type="limit"
        )
        
        if result:
            logger.info(f"LIVE ORDER PLACED: {result}")
        else:
            logger.error("LIVE ORDER FAILED")
    
    async def run_shadow(self) -> None:
        """
        Run in SHADOW mode - real-time data, simulated execution.
        """
        if self.mode != ExecutionMode.SHADOW:
            raise ValueError("Engine not in SHADOW mode")
        
        settings = get_settings()
        poll_interval = settings.polymarket_poll_interval_ms / 1000
        
        self._running = True
        logger.info("Starting SHADOW mode - real-time copytrading simulation")
        
        # Setup signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._shutdown_event.set)
        
        while not self._shutdown_event.is_set():
            try:
                # Poll for new gabagool activity
                signals = await self.polymarket.poll_gabagool_activity()
                
                for sig in signals:
                    await self.process_signal(sig)
                
                # Update metrics
                self._update_metrics()
                
                # Log status periodically
                if self._signals_processed > 0 and self._signals_processed % 10 == 0:
                    await self._log_status()
                
                # Wait for next poll
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=poll_interval
                    )
                except asyncio.TimeoutError:
                    pass
                
            except Exception as e:
                logger.error(f"Error in shadow loop: {e}", exc_info=True)
                await asyncio.sleep(5)  # Backoff on error
        
        logger.info("Shadow mode stopped")
    
    async def run_replay(
        self,
        signals: List[CopySignal],
        latencies: List[int] = [2000, 5000, 10000]
    ) -> dict:
        """
        Run replay mode - process stored signals with varying latencies.
        
        Args:
            signals: List of CopySignals to replay
            latencies: List of latencies to test (in ms)
            
        Returns:
            Summary metrics for each latency
        """
        logger.info(f"Starting replay of {len(signals)} signals")
        
        results = {}
        
        for latency in latencies:
            logger.info(f"Testing latency: {latency}ms")
            
            # Reset simulators
            self.poly_sim = PolymarketSimulator(self.repository)
            self.kalshi_sim = KalshiSimulator(
                kalshi_adapter=self.kalshi,
                repository=self.repository,
                latency_ms=latency
            )
            
            for sig in signals:
                await self.process_signal(sig)
            
            results[f"{latency}ms"] = {
                "polymarket": self.poly_sim.get_metrics(),
                "kalshi": self.kalshi_sim.get_metrics()
            }
        
        # Generate comparison
        comparison = self.kalshi_sim.get_latency_comparison()
        results["latency_comparison"] = comparison
        
        logger.info("Replay complete")
        return results
    
    def _update_metrics(self) -> None:
        """Update Prometheus metrics."""
        # Mapping rate
        if self.kalshi_sim.signals_processed > 0:
            mapping_rate = self.kalshi_sim.signals_mapped / self.kalshi_sim.signals_processed
            self.metrics.set_mapping_success_rate(mapping_rate)
        
        # Fill rate
        kalshi_metrics = self.kalshi_sim.get_metrics()
        self.metrics.set_fill_rate(kalshi_metrics["fill_rate"])
        
        # PnL
        self.metrics.set_pnl("POLYMARKET", self.poly_sim.ledger.total_realized_pnl)
        self.metrics.set_pnl("KALSHI", self.kalshi_sim.ledger.total_realized_pnl)
        
        # Positions
        self.metrics.set_open_positions("POLYMARKET", len(self.poly_sim.ledger.open_positions))
        self.metrics.set_open_positions("KALSHI", len(self.kalshi_sim.ledger.open_positions))
        
        # Circuit breaker
        if self.learner:
            self.metrics.set_circuit_breaker(self.learner.circuit_breaker_active)
    
    async def _log_status(self) -> None:
        """Log current status."""
        poly_metrics = self.poly_sim.get_metrics()
        kalshi_metrics = self.kalshi_sim.get_metrics()
        
        logger.info(
            f"STATUS | "
            f"Signals: {self._signals_processed} | "
            f"POLY: ${poly_metrics['total_realized_pnl']:+.2f} | "
            f"KALSHI: ${kalshi_metrics['total_realized_pnl']:+.2f} "
            f"(fill: {kalshi_metrics['fill_rate']:.1%}, slip: {kalshi_metrics['avg_slippage_bps']:.1f}bps)"
        )
    
    async def _get_status(self) -> dict:
        """Get detailed status for health endpoint."""
        uptime = (datetime.utcnow() - self._start_time).total_seconds() if self._start_time else 0
        
        return {
            "mode": self.mode.value,
            "run_id": self._run_id,
            "uptime_seconds": uptime,
            "signals_processed": self._signals_processed,
            "polymarket_sim": self.poly_sim.get_metrics() if self.poly_sim else {},
            "kalshi_sim": self.kalshi_sim.get_metrics() if self.kalshi_sim else {},
            "learner": self.learner.get_stats() if self.learner else {},
        }
    
    async def _check_database_health(self):
        """Check database health."""
        if self.database and self.database.is_initialized:
            return True, "connected"
        return False, "not connected"
    
    async def _check_polymarket_health(self):
        """Check Polymarket adapter health."""
        if self.polymarket and self.polymarket.is_connected:
            return True, "connected"
        if self.mode == ExecutionMode.SIM:
            return True, "not needed (SIM mode)"
        return False, "not connected"
    
    async def _check_kalshi_health(self):
        """Check Kalshi adapter health."""
        if self.kalshi and self.kalshi.is_connected:
            auth_status = "authenticated" if self.kalshi._authenticated else "read-only"
            return True, auth_status
        if self.mode == ExecutionMode.SIM:
            return True, "not needed (SIM mode)"
        return False, "not connected"

