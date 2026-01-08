"""Main entry point for Kalshi 15-Minute BTC Direction Assistant."""

import asyncio
import argparse
import sys
from pathlib import Path

from src.config import get_config
from src.logger import setup_logging, get_logger, StructuredLogger, TradeLogger, LatencyLogger
from src.data.brti_feed import BRTIFeed
from src.data.kalshi_client import KalshiClient
from src.data.polymarket_overlay import PolymarketOverlay
from src.models.settlement_engine import SettlementEngine
from src.models.probability_model import ProbabilityModel
from src.models.edge_detector import EdgeDetector
from src.strategy.signal_generator import SignalGenerator
from src.strategy.risk_manager import RiskManager
from src.execution.paper_trader import PaperTrader
from src.execution.live_trader import LiveTrader
from src.ui.console import ConsoleUI
from src.ui.alerts import AlertManager
from src.backtest.engine import BacktestEngine


class TradingSystem:
    """Main trading system orchestrator."""
    
    def __init__(self, config_path: str = None):
        """Initialize trading system.
        
        Args:
            config_path: Path to config file
        """
        # Load configuration
        self.config = get_config(config_path)
        self.config.validate()
        
        # Setup logging
        setup_logging(
            level=self.config.get("logging.level", "INFO"),
            log_format=self.config.get("logging.format", "json"),
            log_dir="logs",
            console_enabled=self.config.get("logging.console.enabled", True)
        )
        
        self.logger = StructuredLogger(__name__)
        
        # Create specialized loggers
        self.trade_logger = TradeLogger("logs/trades.json")
        self.latency_logger = LatencyLogger("logs/latency.json")
        
        # Initialize components
        self.brti_feed: Optional[BRTIFeed] = None
        self.kalshi_client: Optional[KalshiClient] = None
        self.polymarket_overlay: Optional[PolymarketOverlay] = None
        self.settlement_engine: Optional[SettlementEngine] = None
        self.probability_model: Optional[ProbabilityModel] = None
        self.edge_detector: Optional[EdgeDetector] = None
        self.signal_generator: Optional[SignalGenerator] = None
        self.risk_manager: Optional[RiskManager] = None
        self.paper_trader: Optional[PaperTrader] = None
        self.live_trader: Optional[LiveTrader] = None
        self.alert_manager: Optional[AlertManager] = None
        self.console_ui: Optional[ConsoleUI] = None
        
        self.logger.info("Trading system initialized")
    
    async def initialize(self) -> None:
        """Initialize all components."""
        self.logger.info("Initializing components...")
        
        # BRTI Feed
        self.brti_feed = BRTIFeed(
            use_cf_benchmarks=self.config.get("data_sources.brti.use_cf_benchmarks", False),
            cf_api_key=self.config.get("data_sources.brti.cf_api_key", ""),
            fallback_exchanges=self.config.get("data_sources.brti.fallback_exchanges", []),
            update_interval=self.config.get("data_sources.brti.update_interval", 1.0),
            buffer_size=self.config.get("data_sources.brti.buffer_size", 300)
        )
        self.brti_feed.set_latency_logger(self.latency_logger)
        await self.brti_feed.start()
        
        # Kalshi Client
        self.kalshi_client = KalshiClient(
            api_key_id=self.config.kalshi_api_key_id,
            private_key_path=self.config.kalshi_private_key_path,
            base_url=self.config.kalshi_base_url,
            ws_url=self.config.kalshi_ws_url
        )
        self.kalshi_client.set_latency_logger(self.latency_logger)
        await self.kalshi_client.start()
        
        # Polymarket Overlay (optional)
        if self.config.get("polymarket.enabled", False):
            self.polymarket_overlay = PolymarketOverlay(
                enabled=True,
                clob_api_url=self.config.get("polymarket.clob_api_url", ""),
                gamma_api_url=self.config.get("polymarket.gamma_api_url", "")
            )
            await self.polymarket_overlay.start()
        
        # Settlement Engine
        self.settlement_engine = SettlementEngine(
            brti_feed=self.brti_feed,
            convention=self.config.settlement_convention,
            log_both=self.config.get("settlement.log_both", True)
        )
        
        # Probability Model
        self.probability_model = ProbabilityModel(
            brti_feed=self.brti_feed,
            settlement_engine=self.settlement_engine,
            num_simulations=self.config.num_monte_carlo_sims,
            volatility_window=self.config.get("probability.volatility_window", 180),
            random_seed=self.config.get("probability.monte_carlo.random_seed", 42)
        )
        
        # Edge Detector
        self.edge_detector = EdgeDetector(
            probability_model=self.probability_model,
            min_edge_threshold=self.config.min_edge_threshold,
            fee_buffer=self.config.get("edge_detection.buffers.fee", 0.007),
            slippage_buffer=self.config.get("edge_detection.buffers.slippage", 0.005),
            latency_buffer=self.config.get("edge_detection.buffers.latency", 0.003),
            delay_window_min_seconds=self.config.get("edge_detection.delay_window.min_seconds", 30),
            delay_window_max_seconds=self.config.get("edge_detection.delay_window.max_seconds", 600)
        )
        self.edge_detector.set_latency_logger(self.latency_logger)
        
        # Signal Generator
        self.signal_generator = SignalGenerator(
            brti_feed=self.brti_feed,
            settlement_engine=self.settlement_engine,
            probability_model=self.probability_model,
            edge_detector=self.edge_detector,
            enable_delay_capture=self.config.get("strategy.signals.delay_capture.enabled", True),
            enable_momentum=self.config.get("strategy.signals.momentum_confirmation.enabled", True),
            enable_baseline_gap=self.config.get("strategy.signals.baseline_gap_at_open.enabled", True)
        )
        
        # Risk Manager
        self.risk_manager = RiskManager(
            initial_bankroll_usd=self.config.initial_bankroll,
            max_risk_per_trade_usd=self.config.max_risk_per_trade_usd,
            max_open_exposure_usd=self.config.max_open_exposure_usd,
            daily_loss_limit_usd=self.config.daily_loss_limit_usd
        )
        
        # Alert Manager
        self.alert_manager = AlertManager(
            desktop_enabled=self.config.get("alerts.desktop.enabled", True),
            telegram_enabled=self.config.get("alerts.telegram.enabled", False),
            telegram_bot_token=self.config.get("alerts.telegram.bot_token", ""),
            telegram_chat_id=self.config.get("alerts.telegram.chat_id", ""),
            webhook_enabled=self.config.get("alerts.webhook.enabled", False),
            webhook_url=self.config.get("alerts.webhook.url", "")
        )
        await self.alert_manager.start()
        
        # Paper Trader
        if self.config.paper_trading_enabled:
            self.paper_trader = PaperTrader(
                risk_manager=self.risk_manager,
                alert_manager=self.alert_manager,
                trade_logger=self.trade_logger
            )
            await self.paper_trader.start()
        
        # Live Trader (disabled by default)
        if self.config.live_trading_enabled:
            self.live_trader = LiveTrader(
                kalshi_client=self.kalshi_client,
                risk_manager=self.risk_manager,
                alert_manager=self.alert_manager,
                trade_logger=self.trade_logger,
                enabled=True,
                confirmation_required=self.config.get("live_trading.confirmation_required", True)
            )
        
        # Console UI
        self.console_ui = ConsoleUI(
            settlement_engine=self.settlement_engine,
            probability_model=self.probability_model,
            edge_detector=self.edge_detector,
            signal_generator=self.signal_generator,
            risk_manager=self.risk_manager,
            refresh_rate=self.config.get("ui.refresh_rate", 2.0),
            compact=self.config.get("ui.compact", False)
        )
        
        self.logger.info("All components initialized")
    
    async def run_live(self) -> None:
        """Run live signal generation mode."""
        self.logger.info("Starting live signal generation mode...")
        
        # Discover active market
        market = await self.kalshi_client.discover_active_btc_15m_market()
        
        if not market:
            self.logger.error("No active BTC 15m market found")
            return
        
        baseline = market.get_baseline()
        settle_timestamp = market.time_to_settle_seconds()
        
        if baseline is None or settle_timestamp is None:
            self.logger.error("Could not determine market parameters")
            return
        
        settle_timestamp = time.time() + settle_timestamp
        
        # Subscribe to market updates
        await self.kalshi_client.subscribe_to_market(market.ticker)
        
        # Set interval start
        self.signal_generator.set_interval_start(baseline, time.time())
        
        # Update UI
        self.console_ui.update_market(market, baseline, settle_timestamp)
        
        # Main loop
        async def update_loop():
            while True:
                try:
                    # Update settlement engine
                    self.settlement_engine.update()
                    
                    # Update probability model
                    self.probability_model.update(baseline, settle_timestamp)
                    
                    # Record underlying update
                    self.edge_detector.record_underlying_update()
                    
                    # Update edge detector
                    self.edge_detector.update(market, settle_timestamp)
                    
                    # Record market update
                    self.edge_detector.record_market_update()
                    
                    # Generate signal
                    recommended_size = self.risk_manager.compute_position_size(
                        edge=self.edge_detector.get_best_edge().edge_net if self.edge_detector.get_best_edge() else 0,
                        confidence=self.probability_model.get_confidence() or 0
                    )
                    
                    signal = self.signal_generator.generate_signal(
                        market=market,
                        baseline=baseline,
                        settle_timestamp=settle_timestamp,
                        recommended_size_usd=recommended_size
                    )
                    
                    if signal:
                        self.console_ui.update_signal(signal)
                        
                        # Log signal
                        self.trade_logger.log_signal(
                            market_id=signal.market_id,
                            side=signal.side,
                            p_true=signal.p_true,
                            p_market=signal.p_market,
                            edge=signal.edge,
                            recommended_size=signal.recommended_size_usd,
                            reason=signal.reason
                        )
                        
                        # Send alert
                        await self.alert_manager.alert_signal(
                            market_id=signal.market_id,
                            side=signal.side,
                            edge=signal.edge,
                            size=signal.recommended_size_usd,
                            reason=signal.reason
                        )
                        
                        # Execute on paper if enabled
                        if self.paper_trader:
                            await self.paper_trader.execute_signal(signal, market)
                    
                    await asyncio.sleep(1)
                
                except Exception as e:
                    self.logger.error(f"Error in update loop: {e}", error=str(e))
                    await asyncio.sleep(1)
        
        # Run UI and update loop concurrently
        await asyncio.gather(
            self.console_ui.run(),
            update_loop()
        )
    
    async def shutdown(self) -> None:
        """Shutdown all components."""
        self.logger.info("Shutting down...")
        
        if self.console_ui:
            self.console_ui.stop()
        
        if self.paper_trader:
            await self.paper_trader.stop()
        
        if self.alert_manager:
            await self.alert_manager.stop()
        
        if self.kalshi_client:
            await self.kalshi_client.stop()
        
        if self.brti_feed:
            await self.brti_feed.stop()
        
        if self.polymarket_overlay:
            await self.polymarket_overlay.stop()
        
        self.logger.info("Shutdown complete")


# Import time for timestamps
import time
from typing import Optional


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Kalshi 15-Minute BTC Direction Assistant"
    )
    
    parser.add_argument(
        "--mode",
        choices=["live", "paper", "backtest", "sweep"],
        default="live",
        help="Operation mode"
    )
    
    parser.add_argument(
        "--config",
        type=str,
        help="Path to config file"
    )
    
    parser.add_argument(
        "--start",
        type=str,
        help="Start date for backtest (YYYY-MM-DD)"
    )
    
    parser.add_argument(
        "--end",
        type=str,
        help="End date for backtest (YYYY-MM-DD)"
    )
    
    parser.add_argument(
        "--market-id",
        type=str,
        help="Manual market ID"
    )
    
    args = parser.parse_args()
    
    # Create system
    system = TradingSystem(config_path=args.config)
    
    try:
        await system.initialize()
        
        if args.mode == "live":
            await system.run_live()
        
        elif args.mode == "backtest":
            print("Backtest mode - implementation in progress")
            # TODO: Implement backtest mode
        
        else:
            print(f"Mode {args.mode} not yet implemented")
    
    except KeyboardInterrupt:
        print("\nShutdown requested...")
    
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        await system.shutdown()


if __name__ == "__main__":
    asyncio.run(main())

