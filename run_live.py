#!/usr/bin/env python3
"""
Live trading system with real BTC data and Kalshi markets.

This script runs continuously, tracking live Bitcoin prices and
making predictions on active Kalshi 15-minute markets.
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime
import signal

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.config import Config
from src.logger import setup_logging, StructuredLogger
import yaml
from src.data.live_btc_feed import LiveBTCFeed
from src.data.kalshi_client import KalshiClient
from src.tracking.trade_tracker import TradeTracker, TradeRecord, PredictionRecord


# Simple predictor (same as simulation)
import numpy as np

class LivePredictor:
    """Live prediction model for 15-minute BTC direction."""
    
    def __init__(self):
        self.name = "Momentum + Mean Reversion Hybrid"
    
    def predict(self, prices, baseline):
        """
        Predict probability that price at T will be > baseline.
        
        Args:
            prices: List of recent prices (at least 60)
            baseline: Starting price for the interval
        
        Returns:
            (p_yes, p_no) tuple
        """
        if len(prices) < 60:
            return None, None
        
        prices = np.array(prices)
        current = prices[-1]
        
        # Recent momentum
        mom_5min = (current - prices[-5]) / prices[-5] if len(prices) >= 5 else 0
        mom_10min = (current - prices[-10]) / prices[-10] if len(prices) >= 10 else 0
        mom_15min = (current - prices[-15]) / prices[-15] if len(prices) >= 15 else 0
        
        # Trend strength
        recent_prices = prices[-15:]
        trend_score = 0
        for i in range(len(recent_prices) - 1):
            if recent_prices[i+1] > recent_prices[i]:
                trend_score += 1
            else:
                trend_score -= 1
        trend_strength = trend_score / (len(recent_prices) - 1)
        
        # Volatility
        returns = np.diff(prices[-60:]) / prices[-60:-1]
        volatility = np.std(returns)
        
        # Distance from baseline
        baseline_gap = (current - baseline) / baseline
        
        # Calculate probability
        p_yes = 0.5
        
        # Strong momentum component
        momentum_signal = (0.5 * mom_5min + 0.3 * mom_10min + 0.2 * mom_15min)
        p_yes += momentum_signal * 50.0
        
        # Trend continuation
        p_yes += trend_strength * 0.15
        
        # Position relative to baseline
        if current > baseline and momentum_signal > 0:
            p_yes += 0.08
        elif current < baseline and momentum_signal < 0:
            p_yes -= 0.08
        
        # Mean reversion for extreme moves
        if abs(baseline_gap) > 0.02:
            p_yes -= baseline_gap * 5.0
        
        # Volatility dampening
        dampening = 1 - (volatility * 1000)
        dampening = np.clip(dampening, 0.7, 1.0)
        p_yes = 0.5 + (p_yes - 0.5) * dampening
        
        # Clip
        p_yes = np.clip(p_yes, 0.05, 0.95)
        p_no = 1 - p_yes
        
        return p_yes, p_no


class LiveTradingSystem:
    """Main live trading system."""
    
    def __init__(self, config_path: str = "config.yaml", paper_mode: bool = True):
        # Load config
        try:
            with open(config_path, 'r') as f:
                self.config = yaml.safe_load(f) or {}
        except FileNotFoundError:
            self.config = {}
        
        self.paper_mode = paper_mode
        self.running = False
        
        # Initialize logger
        setup_logging(level="INFO", log_format="text")
        self.logger = StructuredLogger(__name__)
        
        # Components
        self.btc_feed = LiveBTCFeed(buffer_size=300)
        self.predictor = LivePredictor()
        self.tracker = TradeTracker()
        
        # Kalshi client (optional for market discovery)
        api_key_id = self.config.get("kalshi", {}).get("api_key_id")
        private_key_path = self.config.get("kalshi", {}).get("private_key_path")
        
        self.kalshi_client = None
        if api_key_id and private_key_path:
            try:
                with open(private_key_path, 'r') as f:
                    private_key = f.read()
                self.kalshi_client = KalshiClient(
                    api_key_id=api_key_id,
                    private_key_pem=private_key
                )
            except Exception as e:
                self.logger.warning(f"Kalshi client not available: {e}")
        
        # Trading parameters
        self.min_edge_threshold = 0.015  # 1.5%
        self.min_confidence = 0.03  # 3%
        self.max_position_size = 15.0
        
        # Active markets tracking
        self.active_markets = {}
        self.monitored_markets = set()
    
    async def start(self):
        """Start the live trading system."""
        self.running = True
        
        self.logger.info("=" * 80)
        self.logger.info("🚀 STARTING LIVE TRADING SYSTEM")
        self.logger.info("=" * 80)
        self.logger.info(f"Mode: {'PAPER TRADING' if self.paper_mode else 'LIVE TRADING'}")
        self.logger.info(f"Model: {self.predictor.name}")
        self.logger.info(f"Starting Balance: ${self.tracker.balance:.2f}")
        self.logger.info("=" * 80)
        
        # Start BTC feed
        self.logger.info("Starting live Bitcoin feed...")
        await self.btc_feed.start()
        self.logger.info(f"✓ BTC Feed connected: {self.btc_feed.source}")
        self.logger.info(f"✓ Current price: ${self.btc_feed.get_current_price():,.2f}")
        
        # Start Kalshi client if available
        if self.kalshi_client:
            try:
                await self.kalshi_client.start()
                self.logger.info("✓ Kalshi client connected")
            except Exception as e:
                self.logger.warning(f"Kalshi client failed: {e}")
                self.kalshi_client = None
        
        self.logger.info("")
        self.logger.info("=" * 80)
        self.logger.info("✅ SYSTEM READY - MONITORING FOR OPPORTUNITIES")
        self.logger.info("=" * 80)
        self.logger.info("")
        
        # Run main loop
        await self.main_loop()
    
    async def stop(self):
        """Stop the system."""
        self.running = False
        self.logger.info("Stopping system...")
        
        await self.btc_feed.stop()
        
        if self.kalshi_client:
            await self.kalshi_client.stop()
        
        # Export final results
        self.tracker.export_csv()
        self.tracker.print_summary()
        
        self.logger.info("System stopped.")
    
    async def main_loop(self):
        """Main monitoring loop."""
        iteration = 0
        last_summary = 0
        
        while self.running:
            iteration += 1
            
            try:
                # Check if we have enough data
                buffer = self.btc_feed.get_price_buffer()
                
                if len(buffer) < 60:
                    self.logger.info(f"Warming up... {len(buffer)}/60 prices")
                    await asyncio.sleep(2)
                    continue
                
                # Get current state
                current_price = self.btc_feed.get_current_price()
                avg60 = self.btc_feed.get_avg60()
                
                # Discover active markets (if Kalshi connected)
                if self.kalshi_client and iteration % 30 == 0:  # Every 30 iterations
                    await self.discover_markets()
                
                # For now, create synthetic 15-min markets
                # In production, this would come from Kalshi API
                market_id = f"BTC-15M-{datetime.now().strftime('%Y%m%d-%H%M')}"
                
                # Only process each market once
                if market_id not in self.monitored_markets:
                    await self.process_market(market_id, current_price)
                    self.monitored_markets.add(market_id)
                
                # Print summary every 60 seconds
                if iteration - last_summary >= 60:
                    await self.print_status()
                    last_summary = iteration
                
                # Sleep briefly
                await asyncio.sleep(1)
            
            except Exception as e:
                self.logger.error(f"Error in main loop: {e}", exc_info=True)
                await asyncio.sleep(5)
    
    async def discover_markets(self):
        """Discover active Kalshi BTC 15-minute markets."""
        if not self.kalshi_client:
            return
        
        try:
            market = await self.kalshi_client.discover_active_btc_15m_market()
            if market:
                self.logger.info(f"Discovered market: {market.ticker}")
                self.active_markets[market.ticker] = market
        except Exception as e:
            self.logger.debug(f"Market discovery error: {e}")
    
    async def process_market(self, market_id: str, baseline: float):
        """Process a market and potentially make a trade."""
        # Get price history
        buffer = self.btc_feed.get_price_buffer()
        prices = [p['price'] for p in buffer]
        
        # Make prediction
        p_yes, p_no = self.predictor.predict(prices, baseline)
        
        if p_yes is None:
            return
        
        # Determine prediction
        predicted_outcome = "YES" if p_yes > 0.5 else "NO"
        confidence = abs(p_yes - 0.5)
        
        # Simulate market price (in production, get from Kalshi orderbook)
        # For now, assume market is slightly inefficient
        market_noise = np.random.normal(0, 0.05)
        market_lag = -0.15 * (p_yes - 0.5)
        market_price_yes = np.clip(0.50 + market_noise + market_lag, 0.15, 0.85)
        
        # Calculate edge
        edge_yes = p_yes - market_price_yes - 0.015
        edge_no = p_no - (1 - market_price_yes) - 0.015
        
        best_edge = max(edge_yes, edge_no)
        best_side = "YES" if edge_yes > edge_no else "NO"
        
        # Record prediction
        pred = PredictionRecord(
            timestamp=datetime.now().isoformat(),
            market_id=market_id,
            ticker=market_id,
            baseline=baseline,
            current_price=prices[-1],
            p_yes=p_yes,
            p_no=p_no,
            confidence=confidence,
            predicted_outcome=predicted_outcome,
            market_price_yes=market_price_yes,
            edge=best_edge,
            traded=False
        )
        
        # Trading decision
        should_trade = (
            best_edge >= self.min_edge_threshold and
            confidence >= self.min_confidence and
            self.tracker.balance >= self.max_position_size
        )
        
        if should_trade:
            # Calculate position size
            edge_pct = best_edge / 0.5
            kelly_fraction = min(0.25, edge_pct)
            size = self.tracker.balance * kelly_fraction * 0.5  # Half-Kelly
            size = min(size, self.max_position_size, self.tracker.balance)
            size = max(size, 2.0)
            
            entry_price = market_price_yes if best_side == "YES" else (1 - market_price_yes)
            
            # Create trade
            trade = TradeRecord(
                timestamp=datetime.now().isoformat(),
                market_id=market_id,
                ticker=market_id,
                side=best_side,
                size=size,
                entry_price=entry_price,
                p_true=p_yes if best_side == "YES" else p_no,
                p_market=market_price_yes if best_side == "YES" else (1 - market_price_yes),
                edge=best_edge,
                confidence=confidence,
                status="open",
                baseline=baseline
            )
            
            # Execute trade
            if self.tracker.open_trade(trade):
                pred.traded = True
                
                self.logger.info("")
                self.logger.info("🎯 " + "=" * 76)
                self.logger.info(f"   NEW TRADE SIGNAL")
                self.logger.info("=" * 80)
                self.logger.info(f"   Market:      {market_id}")
                self.logger.info(f"   Side:        {best_side}")
                self.logger.info(f"   Size:        ${size:.2f}")
                self.logger.info(f"   Entry:       {entry_price:.3f}")
                self.logger.info(f"   P(True):     {p_yes if best_side == 'YES' else p_no:.1%}")
                self.logger.info(f"   Edge:        {best_edge:.1%}")
                self.logger.info(f"   Confidence:  {confidence:.1%}")
                self.logger.info(f"   Balance:     ${self.tracker.balance:.2f}")
                self.logger.info("=" * 80)
                self.logger.info("")
        
        # Record prediction
        self.tracker.record_prediction(pred)
    
    async def print_status(self):
        """Print current system status."""
        stats = self.tracker.get_stats()
        feed_stats = self.btc_feed.get_stats()
        
        self.logger.info("")
        self.logger.info("─" * 80)
        self.logger.info(f"💰 Balance: ${stats['balance']:.2f} | "
                        f"P&L: ${stats['total_pnl']:+.2f} ({stats['roi']:+.1%}) | "
                        f"Trades: {stats['total_trades']} | "
                        f"Win Rate: {stats['win_rate']:.1%}")
        self.logger.info(f"📊 BTC: ${feed_stats['current_price']:,.2f} | "
                        f"Source: {feed_stats['source']} | "
                        f"Buffer: {feed_stats['buffer_size']}")
        self.logger.info("─" * 80)
        self.logger.info("")


async def main():
    """Main entry point."""
    # Parse args
    paper_mode = True  # Always paper mode for now
    
    system = LiveTradingSystem(paper_mode=paper_mode)
    
    # Handle graceful shutdown
    def signal_handler(sig, frame):
        print("\n\nShutting down gracefully...")
        asyncio.create_task(system.stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await system.start()
    except KeyboardInterrupt:
        print("\n\nShutting down...")
    finally:
        await system.stop()


if __name__ == "__main__":
    asyncio.run(main())

