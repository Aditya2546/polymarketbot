#!/usr/bin/env python3
"""
Auto Settler - Runs continuously to settle expired trades.

Checks all strategies every 60 seconds and settles any trades
that have been open for 15+ minutes.
"""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from src.data.live_btc_feed import LiveBTCFeed
from src.logger import setup_logging, StructuredLogger


class AutoSettler:
    def __init__(self):
        setup_logging(level="INFO", log_format="text")
        self.logger = StructuredLogger(__name__)
        self.btc_feed = LiveBTCFeed()
        self.running = False
        
        # Strategies to settle
        self.strategies = [
            {
                'name': 'Strategy 1 (Hybrid)',
                'trades_file': Path('data/strategy1_hybrid/trades.jsonl'),
                'perf_file': Path('data/strategy1_hybrid/performance.json'),
                'size_field': 'size'
            },
            {
                'name': 'Strategy 2 (Momentum)',
                'trades_file': Path('data/strategy2_momentum/trades.jsonl'),
                'perf_file': Path('data/strategy2_momentum/performance.json'),
                'size_field': 'size'
            },
            {
                'name': 'Strategy 3 (Adaptive)',
                'trades_file': Path('data/strategy3_adaptive/trades.jsonl'),
                'perf_file': Path('data/strategy3_adaptive/performance.json'),
                'size_field': 'size'
            },
            {
                'name': 'Copy @gabagool22',
                'trades_file': Path('data/copy_trading/copy_trades.jsonl'),
                'perf_file': Path('data/copy_trading/performance.json'),
                'size_field': 'copy_size'
            },
        ]
    
    async def start(self):
        self.running = True
        self.logger.info("=" * 70)
        self.logger.info("🔄 AUTO SETTLER - Starting")
        self.logger.info("=" * 70)
        self.logger.info("Settling trades every 60 seconds for all strategies")
        self.logger.info("")
        
        await self.btc_feed.start()
        self.logger.info(f"✓ BTC Feed connected: {self.btc_feed.source}")
        
        await self.main_loop()
    
    async def stop(self):
        self.running = False
        await self.btc_feed.stop()
        self.logger.info("Auto settler stopped")
    
    async def main_loop(self):
        while self.running:
            try:
                btc_price = self.btc_feed.get_current_price()
                
                if btc_price:
                    total_settled = 0
                    total_pnl = 0
                    
                    for strategy in self.strategies:
                        settled, pnl = self.settle_strategy(strategy, btc_price)
                        total_settled += settled
                        total_pnl += pnl
                    
                    if total_settled > 0:
                        self.logger.info("")
                        self.logger.info(f"📊 Settled {total_settled} trades | P&L: ${total_pnl:+.2f}")
                        self.logger.info("")
                
                await asyncio.sleep(60)  # Check every 60 seconds
                
            except Exception as e:
                self.logger.error(f"Error in settlement loop: {e}")
                await asyncio.sleep(10)
    
    def settle_strategy(self, strategy: dict, btc_price: float) -> tuple:
        """Settle expired trades for a strategy. Returns (count, pnl)."""
        
        trades_file = strategy['trades_file']
        perf_file = strategy['perf_file']
        size_field = strategy['size_field']
        name = strategy['name']
        
        if not trades_file.exists():
            return 0, 0
        
        now = datetime.now()
        all_trades = []
        
        # Read all trades
        with open(trades_file, 'r') as f:
            for line in f:
                try:
                    all_trades.append(json.loads(line))
                except:
                    continue
        
        settled_count = 0
        total_pnl = 0
        balance_change = 0
        
        for trade in all_trades:
            if trade.get('status') != 'open':
                continue
            
            # Parse timestamp
            try:
                trade_time = datetime.fromisoformat(trade['timestamp'])
            except:
                continue
            
            # Check if 15+ minutes old
            elapsed = (now - trade_time).total_seconds() / 60
            
            if elapsed >= 15:
                # Get baseline and determine outcome
                baseline = trade.get('baseline', btc_price)
                
                # For copy trades, check outcome field
                if 'outcome' in trade:
                    # Copy trade format
                    outcome = trade['outcome']  # "Up" or "Down"
                    actual = "Up" if btc_price > baseline else "Down"
                    won = (outcome == actual)
                    side = outcome
                else:
                    # Regular trade format
                    actual = "YES" if btc_price > baseline else "NO"
                    side = trade.get('side', 'YES')
                    won = (side == actual)
                
                # Calculate P&L
                size = trade.get(size_field, 0)
                price = trade.get('entry_price', trade.get('copy_price', 0.5))
                
                if won:
                    payout = size / price if price > 0 else size
                    pnl = payout - size
                else:
                    payout = 0
                    pnl = -size
                
                # Update trade
                trade['status'] = 'closed'
                trade['actual_outcome'] = actual
                trade['pnl'] = pnl
                trade['close_timestamp'] = now.isoformat()
                trade['won'] = won
                trade['final_price'] = btc_price
                
                balance_change += payout
                total_pnl += pnl
                settled_count += 1
                
                result = "✅" if won else "❌"
                self.logger.info(f"{result} {name}: {side} @ {price:.3f} → {actual} | P&L: ${pnl:+.2f}")
        
        # Save updated trades
        if settled_count > 0:
            with open(trades_file, 'w') as f:
                for trade in all_trades:
                    f.write(json.dumps(trade) + '\n')
            
            # Update performance
            if perf_file.exists():
                with open(perf_file, 'r') as f:
                    perf = json.load(f)
                
                perf['balance'] = perf.get('balance', 0) + balance_change
                perf['last_settlement'] = now.isoformat()
                
                with open(perf_file, 'w') as f:
                    json.dump(perf, f, indent=2)
        
        return settled_count, total_pnl


async def main():
    settler = AutoSettler()
    
    import signal
    def handler(sig, frame):
        print("\nShutting down...")
        asyncio.create_task(settler.stop())
    
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
    
    try:
        await settler.start()
    except KeyboardInterrupt:
        pass
    finally:
        await settler.stop()


if __name__ == "__main__":
    asyncio.run(main())

