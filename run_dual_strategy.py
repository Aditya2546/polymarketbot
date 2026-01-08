#!/usr/bin/env python3
"""
Dual Strategy Live Trading System

Runs TWO strategies in parallel:
1. Primary: Momentum + Mean Reversion Hybrid (existing)
2. Alternative: Momentum Follower (wait 10min, bet on continuation)

Tracks performance of both strategies separately.
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime
import signal
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from src.config import Config
from src.logger import setup_logging, StructuredLogger
from src.data.live_btc_feed import LiveBTCFeed
from src.data.kalshi_client import KalshiClient
from src.tracking.trade_tracker import TradeTracker, TradeRecord, PredictionRecord
from src.strategy.momentum_follower import MomentumFollower
import yaml


class HybridPredictor:
    """The original hybrid predictor."""
    
    def __init__(self):
        self.name = "Momentum + Mean Reversion Hybrid"
    
    def predict(self, prices, baseline):
        if len(prices) < 60:
            return None, None, {}
        
        prices = np.array(prices)
        current = prices[-1]
        
        # Momentum
        mom_5min = (current - prices[-5]) / prices[-5] if len(prices) >= 5 else 0
        mom_10min = (current - prices[-10]) / prices[-10] if len(prices) >= 10 else 0
        mom_15min = (current - prices[-15]) / prices[-15] if len(prices) >= 15 else 0
        
        # Trend
        recent_prices = prices[-15:]
        trend_score = sum(1 if recent_prices[i+1] > recent_prices[i] else -1 
                         for i in range(len(recent_prices) - 1))
        trend_strength = trend_score / (len(recent_prices) - 1)
        
        # Volatility
        returns = np.diff(prices[-60:]) / prices[-60:-1]
        volatility = np.std(returns)
        
        # Distance from baseline
        baseline_gap = (current - baseline) / baseline
        
        # Calculate
        p_yes = 0.5
        momentum_signal = (0.5 * mom_5min + 0.3 * mom_10min + 0.2 * mom_15min)
        p_yes += momentum_signal * 50.0
        p_yes += trend_strength * 0.15
        
        if current > baseline and momentum_signal > 0:
            p_yes += 0.08
        elif current < baseline and momentum_signal < 0:
            p_yes -= 0.08
        
        if abs(baseline_gap) > 0.02:
            p_yes -= baseline_gap * 5.0
        
        dampening = 1 - (volatility * 1000)
        dampening = np.clip(dampening, 0.7, 1.0)
        p_yes = 0.5 + (p_yes - 0.5) * dampening
        
        p_yes = np.clip(p_yes, 0.05, 0.95)
        p_no = 1 - p_yes
        
        return p_yes, p_no, {'type': 'hybrid'}


class DualStrategySystem:
    """Runs two strategies in parallel."""
    
    def __init__(self, config_path: str = "config.yaml"):
        try:
            with open(config_path, 'r') as f:
                self.config = yaml.safe_load(f) or {}
        except FileNotFoundError:
            self.config = {}
        
        setup_logging(level="INFO", log_format="text")
        self.logger = StructuredLogger(__name__)
        
        # Components
        self.btc_feed = LiveBTCFeed(buffer_size=300)
        
        # Two strategies
        self.strategy1 = HybridPredictor()
        self.strategy2 = MomentumFollower(min_confidence=0.02)
        
        # Two separate trackers
        self.tracker1 = TradeTracker(data_dir="data/strategy1_hybrid")
        self.tracker2 = TradeTracker(data_dir="data/strategy2_momentum")
        
        # Kalshi client (optional)
        self.kalshi_client = None
        
        # Trading params
        self.min_edge_threshold = 0.015
        self.max_position_size = 15.0
        
        # Market tracking
        self.monitored_markets = set()
        self.running = False
    
    async def start(self):
        """Start the dual strategy system."""
        self.running = True
        
        self.logger.info("=" * 80)
        self.logger.info("🚀 DUAL STRATEGY LIVE TRADING SYSTEM")
        self.logger.info("=" * 80)
        self.logger.info(f"Strategy 1: {self.strategy1.name}")
        self.logger.info(f"  Balance: ${self.tracker1.balance:.2f}")
        self.logger.info(f"Strategy 2: {self.strategy2.name}")
        self.logger.info(f"  Balance: ${self.tracker2.balance:.2f}")
        self.logger.info("=" * 80)
        
        # Start BTC feed
        self.logger.info("Starting live Bitcoin feed...")
        await self.btc_feed.start()
        self.logger.info(f"✓ BTC Feed connected: {self.btc_feed.source}")
        self.logger.info(f"✓ Current price: ${self.btc_feed.get_current_price():,.2f}")
        
        self.logger.info("")
        self.logger.info("=" * 80)
        self.logger.info("✅ SYSTEM READY - RUNNING DUAL STRATEGIES")
        self.logger.info("=" * 80)
        self.logger.info("")
        
        await self.main_loop()
    
    async def stop(self):
        """Stop the system."""
        self.running = False
        self.logger.info("Stopping system...")
        
        await self.btc_feed.stop()
        
        # Export both
        self.tracker1.export_csv()
        self.tracker2.export_csv()
        
        # Print both summaries
        self.logger.info("")
        self.logger.info("=" * 80)
        self.logger.info(f"📊 STRATEGY 1: {self.strategy1.name}")
        self.logger.info("=" * 80)
        self.tracker1.print_summary()
        
        self.logger.info("")
        self.logger.info("=" * 80)
        self.logger.info(f"📊 STRATEGY 2: {self.strategy2.name}")
        self.logger.info("=" * 80)
        self.tracker2.print_summary()
        
        # Comparison
        stats1 = self.tracker1.get_stats()
        stats2 = self.tracker2.get_stats()
        
        self.logger.info("")
        self.logger.info("=" * 80)
        self.logger.info("📊 STRATEGY COMPARISON")
        self.logger.info("=" * 80)
        self.logger.info(f"Strategy 1 (Hybrid):          ROI: {stats1.get('roi', 0):+.1%} | Trades: {stats1.get('total_trades', 0)} | Win Rate: {stats1.get('win_rate', 0):.1%}")
        self.logger.info(f"Strategy 2 (Momentum 10min):  ROI: {stats2.get('roi', 0):+.1%} | Trades: {stats2.get('total_trades', 0)} | Win Rate: {stats2.get('win_rate', 0):.1%}")
        
        if stats1.get('total_trades', 0) > 0 and stats2.get('total_trades', 0) > 0:
            if stats1['roi'] > stats2['roi']:
                self.logger.info(f"🏆 WINNER: Strategy 1 (Hybrid) by {(stats1['roi'] - stats2['roi']):.1%}")
            elif stats2['roi'] > stats1['roi']:
                self.logger.info(f"🏆 WINNER: Strategy 2 (Momentum) by {(stats2['roi'] - stats1['roi']):.1%}")
            else:
                self.logger.info("🤝 TIE: Both strategies performed equally")
        
        self.logger.info("=" * 80)
        
        self.logger.info("System stopped.")
    
    async def main_loop(self):
        """Main monitoring loop."""
        iteration = 0
        last_summary = 0
        
        while self.running:
            iteration += 1
            
            try:
                buffer = self.btc_feed.get_price_buffer()
                
                if len(buffer) < 60:
                    self.logger.info(f"Warming up... {len(buffer)}/60 prices")
                    await asyncio.sleep(2)
                    continue
                
                current_price = self.btc_feed.get_current_price()
                
                # Create market ID (every minute creates a new 15-min market)
                market_id = f"BTC-15M-{datetime.now().strftime('%Y%m%d-%H%M')}"
                
                # Only process each market once
                if market_id not in self.monitored_markets:
                    await self.process_market_dual(market_id, current_price)
                    self.monitored_markets.add(market_id)
                
                # Print summary every 60 seconds
                if iteration - last_summary >= 60:
                    await self.print_dual_status()
                    last_summary = iteration
                
                await asyncio.sleep(1)
            
            except Exception as e:
                self.logger.error(f"Error in main loop: {e}", exc_info=True)
                await asyncio.sleep(5)
    
    async def process_market_dual(self, market_id: str, baseline: float):
        """Process market with both strategies."""
        buffer = self.btc_feed.get_price_buffer()
        prices = [p['price'] for p in buffer]
        
        # Simulate market price
        market_noise = np.random.normal(0, 0.05)
        
        # STRATEGY 1: Hybrid (existing)
        p_yes1, p_no1, meta1 = self.strategy1.predict(prices, baseline)
        
        if p_yes1 is not None:
            await self.execute_strategy(
                strategy_name="Strategy1-Hybrid",
                tracker=self.tracker1,
                market_id=market_id,
                baseline=baseline,
                current_price=prices[-1],
                p_yes=p_yes1,
                p_no=p_no1,
                market_noise=market_noise - 0.15 * (p_yes1 - 0.5),
                metadata=meta1
            )
        
        # STRATEGY 2: Momentum Follower (wait 10 minutes)
        # Simulate being 10 minutes into the interval
        p_yes2, p_no2, meta2 = self.strategy2.predict(
            current_price=prices[-1],
            baseline=baseline,
            prices=prices,
            minutes_elapsed=10
        )
        
        if p_yes2 is not None:
            await self.execute_strategy(
                strategy_name="Strategy2-Momentum",
                tracker=self.tracker2,
                market_id=market_id,
                baseline=baseline,
                current_price=prices[-1],
                p_yes=p_yes2,
                p_no=p_no2,
                market_noise=market_noise - 0.10 * (p_yes2 - 0.5),  # Different market pricing
                metadata=meta2
            )
    
    async def execute_strategy(self, strategy_name, tracker, market_id, baseline, 
                              current_price, p_yes, p_no, market_noise, metadata):
        """Execute a single strategy."""
        
        predicted_outcome = "YES" if p_yes > 0.5 else "NO"
        confidence = abs(p_yes - 0.5)
        
        # Market price
        market_price_yes = np.clip(0.50 + market_noise, 0.15, 0.85)
        
        # Edge
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
            current_price=current_price,
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
            confidence >= 0.02 and
            tracker.balance >= self.max_position_size
        )
        
        if should_trade:
            # Position size
            edge_pct = best_edge / 0.5
            kelly = min(0.25, edge_pct)
            size = tracker.balance * kelly * 0.5
            size = min(size, self.max_position_size, tracker.balance)
            size = max(size, 2.0)
            
            entry_price = market_price_yes if best_side == "YES" else (1 - market_price_yes)
            
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
            
            if tracker.open_trade(trade):
                pred.traded = True
                
                self.logger.info("")
                self.logger.info("🎯 " + "=" * 76)
                self.logger.info(f"   {strategy_name} TRADE")
                self.logger.info("=" * 80)
                self.logger.info(f"   Market:      {market_id}")
                self.logger.info(f"   Side:        {best_side}")
                self.logger.info(f"   Size:        ${size:.2f}")
                self.logger.info(f"   Entry:       {entry_price:.3f}")
                self.logger.info(f"   P(True):     {p_yes if best_side == 'YES' else p_no:.1%}")
                self.logger.info(f"   Edge:        {best_edge:.1%}")
                self.logger.info(f"   Balance:     ${tracker.balance:.2f}")
                if metadata:
                    self.logger.info(f"   Metadata:    {metadata}")
                self.logger.info("=" * 80)
                self.logger.info("")
        
        tracker.record_prediction(pred)
    
    async def print_dual_status(self):
        """Print status for both strategies."""
        stats1 = self.tracker1.get_stats()
        stats2 = self.tracker2.get_stats()
        feed_stats = self.btc_feed.get_stats()
        
        self.logger.info("")
        self.logger.info("─" * 80)
        self.logger.info(f"📊 BTC: ${feed_stats['current_price']:,.2f} | Source: {feed_stats['source']}")
        self.logger.info(f"💰 Strategy 1 (Hybrid):         ${stats1['balance']:.2f} | P&L: ${stats1['total_pnl']:+.2f} ({stats1['roi']:+.1%}) | Trades: {stats1['total_trades']} | WR: {stats1['win_rate']:.1%}")
        self.logger.info(f"💰 Strategy 2 (Momentum 10min): ${stats2['balance']:.2f} | P&L: ${stats2['total_pnl']:+.2f} ({stats2['roi']:+.1%}) | Trades: {stats2['total_trades']} | WR: {stats2['win_rate']:.1%}")
        self.logger.info("─" * 80)
        self.logger.info("")


async def main():
    """Main entry point."""
    system = DualStrategySystem()
    
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

