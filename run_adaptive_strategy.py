#!/usr/bin/env python3
"""
Adaptive Strategy Live Trading

My custom strategy that:
1. Adapts based on recent performance
2. Detects trend reversals
3. Uses circuit breakers
4. Hedges when uncertain
"""

import asyncio
import sys
import json
import signal
from pathlib import Path
from datetime import datetime
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from src.logger import setup_logging, StructuredLogger
from src.data.live_btc_feed import LiveBTCFeed
from src.strategy.adaptive_strategy import AdaptiveStrategy
from src.tracking.trade_tracker import TradeTracker, TradeRecord, PredictionRecord


class AdaptiveTradingSystem:
    def __init__(self):
        setup_logging(level="INFO", log_format="text")
        self.logger = StructuredLogger(__name__)
        
        # Components
        self.btc_feed = LiveBTCFeed(buffer_size=300)
        self.strategy = AdaptiveStrategy()
        self.tracker = TradeTracker(data_dir="data/strategy3_adaptive")
        
        # Trading params
        self.max_position_size = 12.0  # Smaller than other strategies
        self.min_position_size = 2.0
        
        # Track markets
        self.processed_markets = set()
        self.running = False
    
    async def start(self):
        self.running = True
        
        self.logger.info("=" * 80)
        self.logger.info("🧠 ADAPTIVE SMART STRATEGY - LIVE")
        self.logger.info("=" * 80)
        self.logger.info(f"Starting balance: ${self.tracker.balance:.2f}")
        self.logger.info("=" * 80)
        
        # Start feed
        await self.btc_feed.start()
        self.logger.info(f"✓ BTC Feed: {self.btc_feed.source}")
        self.logger.info(f"✓ Price: ${self.btc_feed.get_current_price():,.2f}")
        
        self.logger.info("")
        self.logger.info("🟢 SYSTEM LIVE - Adaptive Strategy Running")
        self.logger.info("")
        
        await self.main_loop()
    
    async def stop(self):
        self.running = False
        await self.btc_feed.stop()
        self.tracker.export_csv()
        
        self.logger.info("")
        self.logger.info("=" * 80)
        self.logger.info("📊 FINAL RESULTS - Adaptive Strategy")
        self.logger.info("=" * 80)
        self.tracker.print_summary()
    
    async def main_loop(self):
        iteration = 0
        
        while self.running:
            iteration += 1
            
            try:
                buffer = self.btc_feed.get_price_buffer()
                
                if len(buffer) < 60:
                    self.logger.info(f"Warming up... {len(buffer)}/60")
                    await asyncio.sleep(2)
                    continue
                
                current_price = self.btc_feed.get_current_price()
                market_id = f"BTC-15M-{datetime.now().strftime('%Y%m%d-%H%M')}"
                
                if market_id not in self.processed_markets:
                    await self.process_market(market_id, current_price, buffer)
                    self.processed_markets.add(market_id)
                
                # Status every 30 seconds
                if iteration % 30 == 0:
                    await self.print_status()
                
                await asyncio.sleep(1)
                
            except Exception as e:
                self.logger.error(f"Error: {e}", exc_info=True)
                await asyncio.sleep(5)
    
    async def process_market(self, market_id: str, baseline: float, buffer: list):
        prices = [p['price'] for p in buffer]
        
        # Simulate market price (in real trading, get from Kalshi)
        market_noise = np.random.normal(0, 0.08)
        market_price_yes = np.clip(0.50 + market_noise, 0.20, 0.80)
        
        # Get strategy signal
        side, size_mult, edge, meta = self.strategy.predict(
            prices=prices,
            baseline=baseline,
            market_price_yes=market_price_yes
        )
        
        # Log signal
        action = meta.get('action', 'unknown')
        
        if action == 'skip_low_confidence':
            self.logger.debug(f"⏸ Skip: Low confidence (p_yes={meta['p_yes']:.2f})")
            return
        elif action == 'skip_no_edge':
            self.logger.debug(f"⏸ Skip: No edge detected")
            return
        elif action == 'circuit_breaker':
            self.logger.warning(f"🛑 Circuit breaker active! Cooldown: {meta['cooldown_remaining']}s")
            return
        elif action == 'hedge_uncertain':
            self.logger.info(f"🔀 HEDGE signal - market uncertain")
            # Could implement actual hedging here
            return
        
        if side is None:
            return
        
        # Calculate position size
        base_size = self.tracker.balance * 0.08  # 8% of balance
        size = base_size * size_mult
        size = np.clip(size, self.min_position_size, self.max_position_size)
        size = min(size, self.tracker.balance)
        
        if size < self.min_position_size:
            self.logger.warning(f"Insufficient balance: ${self.tracker.balance:.2f}")
            return
        
        # Entry price
        entry_price = market_price_yes if side == "YES" else (1 - market_price_yes)
        
        # Create trade
        trade = TradeRecord(
            timestamp=datetime.now().isoformat(),
            market_id=market_id,
            ticker=market_id,
            side=side,
            size=size,
            entry_price=entry_price,
            p_true=meta['p_yes'] if side == "YES" else meta['p_no'],
            p_market=entry_price,
            edge=edge,
            confidence=abs(meta['p_yes'] - 0.5),
            status="open",
            baseline=baseline
        )
        
        if self.tracker.open_trade(trade):
            self.logger.info("")
            self.logger.info("🧠 " + "=" * 76)
            self.logger.info(f"   ADAPTIVE STRATEGY TRADE")
            self.logger.info("=" * 80)
            self.logger.info(f"   Side:        {side}")
            self.logger.info(f"   Size:        ${size:.2f} (mult: {size_mult:.2f})")
            self.logger.info(f"   Entry:       {entry_price:.3f}")
            self.logger.info(f"   Edge:        {edge:.1%}")
            self.logger.info(f"   Momentum:    {meta['momentum']*100:.3f}%")
            self.logger.info(f"   Volatility:  {meta['vol_regime']}")
            self.logger.info(f"   Reversal:    {'⚠️ LIKELY' if meta['reversal_likely'] else 'No'}")
            self.logger.info(f"   Adaptation:  {meta['adaptation_factor']:.2f}x")
            self.logger.info(f"   Recent WR:   {meta['recent_win_rate']:.1%}")
            self.logger.info(f"   Balance:     ${self.tracker.balance:.2f}")
            self.logger.info("=" * 80)
            self.logger.info("")
    
    async def print_status(self):
        stats = self.tracker.get_stats()
        feed_stats = self.btc_feed.get_stats()
        
        self.logger.info("")
        self.logger.info("─" * 80)
        self.logger.info(f"🧠 Adaptive | BTC: ${feed_stats['current_price']:,.2f} | "
                        f"Balance: ${stats['balance']:.2f} | "
                        f"P&L: ${stats['total_pnl']:+.2f} | "
                        f"Trades: {stats['total_trades']} | "
                        f"WR: {stats['win_rate']:.1%}")
        self.logger.info("─" * 80)


async def main():
    system = AdaptiveTradingSystem()
    
    def signal_handler(sig, frame):
        print("\n\nShutting down...")
        asyncio.create_task(system.stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await system.start()
    except KeyboardInterrupt:
        pass
    finally:
        await system.stop()


if __name__ == "__main__":
    asyncio.run(main())

