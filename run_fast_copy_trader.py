#!/usr/bin/env python3
"""
HIGH-SPEED COPY TRADER for @gabagool22

Polls every 2 seconds for new trades and executes INSTANTLY.
- Opens positions when gabagool opens
- Closes positions when gabagool closes (SELL trades)
"""

import asyncio
import aiohttp
import json
from datetime import datetime
from pathlib import Path
import sys
from collections import deque

sys.path.insert(0, str(Path(__file__).parent))

from src.logger import setup_logging, StructuredLogger


class FastCopyTrader:
    def __init__(self, wallet: str, balance: float = 200.0):
        setup_logging(level="INFO", log_format="text")
        self.logger = StructuredLogger(__name__)
        
        self.wallet = wallet
        self.balance = balance
        self.initial_balance = balance
        
        # Data storage
        self.data_dir = Path("data/fast_copy_gabagool")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.trades_file = self.data_dir / "trades.jsonl"
        self.perf_file = self.data_dir / "performance.json"
        
        # Track seen trades to avoid duplicates
        self.seen_trades = set()
        self.last_trade_timestamp = 0
        
        # Open positions (market_id -> position info)
        self.positions = {}
        
        # Stats
        self.total_trades = 0
        self.wins = 0
        self.losses = 0
        self.realized_pnl = 0
        
        # Scaling
        self.gabagool_portfolio_value = 50000  # Estimate - will update
        self.our_scale = balance / self.gabagool_portfolio_value
        
        self.running = False
        self.poll_interval = 2  # Poll every 2 seconds
        
        # Load existing state
        self._load_state()
    
    def _load_state(self):
        """Load existing state from disk."""
        if self.perf_file.exists():
            with open(self.perf_file) as f:
                state = json.load(f)
                self.balance = state.get('balance', self.balance)
                self.wins = state.get('wins', 0)
                self.losses = state.get('losses', 0)
                self.realized_pnl = state.get('realized_pnl', 0)
                self.last_trade_timestamp = state.get('last_trade_timestamp', 0)
                self.seen_trades = set(state.get('seen_trades', []))
        
        # Load positions
        if self.trades_file.exists():
            with open(self.trades_file) as f:
                for line in f:
                    trade = json.loads(line)
                    if trade.get('status') == 'open':
                        key = f"{trade['market_id']}_{trade['outcome']}"
                        self.positions[key] = trade
    
    def _save_state(self):
        """Save state to disk."""
        state = {
            'balance': self.balance,
            'wins': self.wins,
            'losses': self.losses,
            'realized_pnl': self.realized_pnl,
            'last_trade_timestamp': self.last_trade_timestamp,
            'seen_trades': list(self.seen_trades)[-1000:],  # Keep last 1000
            'last_update': datetime.now().isoformat()
        }
        with open(self.perf_file, 'w') as f:
            json.dump(state, f, indent=2)
    
    async def start(self):
        self.running = True
        
        self.logger.info("=" * 70)
        self.logger.info("⚡ FAST COPY TRADER - @gabagool22")
        self.logger.info("=" * 70)
        self.logger.info(f"   Wallet: {self.wallet}")
        self.logger.info(f"   Balance: ${self.balance:.2f}")
        self.logger.info(f"   Poll interval: {self.poll_interval}s")
        self.logger.info("=" * 70)
        self.logger.info("")
        self.logger.info("🟢 LIVE - Watching for trades...")
        self.logger.info("")
        
        await self.poll_loop()
    
    async def stop(self):
        self.running = False
        self._save_state()
        self.logger.info("Fast copy trader stopped")
        self.print_summary()
    
    async def poll_loop(self):
        """Main polling loop - checks for new trades every 2 seconds."""
        async with aiohttp.ClientSession() as session:
            while self.running:
                try:
                    await self.check_for_trades(session)
                    await asyncio.sleep(self.poll_interval)
                except Exception as e:
                    self.logger.error(f"Poll error: {e}")
                    await asyncio.sleep(5)
    
    async def check_for_trades(self, session: aiohttp.ClientSession):
        """Check for new trades from gabagool."""
        url = f"https://data-api.polymarket.com/trades?user={self.wallet}&limit=20"
        
        try:
            async with session.get(url, timeout=5) as resp:
                if resp.status != 200:
                    return
                
                trades = await resp.json()
                
                # Process trades in chronological order (oldest first)
                trades.sort(key=lambda x: x.get('timestamp', 0))
                
                for trade in trades:
                    trade_id = f"{trade.get('timestamp')}_{trade.get('conditionId')}_{trade.get('side')}"
                    
                    if trade_id in self.seen_trades:
                        continue
                    
                    # New trade detected!
                    self.seen_trades.add(trade_id)
                    self.last_trade_timestamp = max(self.last_trade_timestamp, trade.get('timestamp', 0))
                    
                    await self.process_trade(trade)
                    
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            self.logger.error(f"API error: {e}")
    
    async def process_trade(self, trade: dict):
        """Process a new trade from gabagool - INSTANT execution."""
        side = trade.get('side', '').upper()  # BUY or SELL
        outcome = trade.get('outcome', 'Unknown')
        title = trade.get('title', 'Unknown')[:50]
        market_id = trade.get('conditionId', '')
        price = float(trade.get('price', 0.5))
        size = float(trade.get('size', 0))
        value = size * price
        
        timestamp = datetime.fromtimestamp(trade.get('timestamp', 0)).strftime('%H:%M:%S')
        
        position_key = f"{market_id}_{outcome}"
        
        if side == "BUY":
            # OPEN POSITION - Mirror the buy
            await self.open_position(trade, position_key)
        elif side == "SELL":
            # CLOSE POSITION - Mirror the sell
            await self.close_position(trade, position_key)
    
    async def open_position(self, trade: dict, position_key: str):
        """Open a position mirroring gabagool's buy."""
        outcome = trade.get('outcome', 'Unknown')
        title = trade.get('title', 'Unknown')[:45]
        price = float(trade.get('price', 0.5))
        gab_size = float(trade.get('size', 0))
        gab_value = gab_size * price
        
        # Calculate our size (scaled)
        our_size = min(gab_value * self.our_scale, self.balance * 0.15, 15.0)
        our_size = max(our_size, 2.0)  # Minimum $2
        
        if our_size > self.balance:
            self.logger.warning(f"⚠️ Insufficient balance: ${self.balance:.2f}")
            return
        
        # Deduct from balance
        self.balance -= our_size
        
        # Create position record
        position = {
            'timestamp': datetime.now().isoformat(),
            'market_id': trade.get('conditionId'),
            'market_title': title,
            'outcome': outcome,
            'side': 'BUY',
            'entry_price': price,
            'size': our_size,
            'gab_size': gab_size,
            'gab_value': gab_value,
            'status': 'open'
        }
        
        self.positions[position_key] = position
        self.total_trades += 1
        
        # Save to file
        with open(self.trades_file, 'a') as f:
            f.write(json.dumps(position) + '\n')
        
        self._save_state()
        
        self.logger.info("")
        self.logger.info("⚡" + "=" * 68)
        self.logger.info(f"   🟢 OPENED: {outcome}")
        self.logger.info(f"   Market: {title}...")
        self.logger.info(f"   Gab: ${gab_value:.2f} ({gab_size:.0f} @ {price:.3f})")
        self.logger.info(f"   Us:  ${our_size:.2f} @ {price:.3f}")
        self.logger.info(f"   Balance: ${self.balance:.2f}")
        self.logger.info("=" * 70)
    
    async def close_position(self, trade: dict, position_key: str):
        """Close a position mirroring gabagool's sell."""
        outcome = trade.get('outcome', 'Unknown')
        title = trade.get('title', 'Unknown')[:45]
        exit_price = float(trade.get('price', 0.5))
        
        if position_key not in self.positions:
            # We don't have this position open - skip
            return
        
        position = self.positions[position_key]
        entry_price = position['entry_price']
        size = position['size']
        
        # Calculate P&L
        # If we bought at entry_price and selling at exit_price
        if exit_price > entry_price:
            # Made money
            pnl = size * (exit_price / entry_price - 1)
            payout = size + pnl
            self.wins += 1
        else:
            # Lost money
            pnl = size * (exit_price / entry_price - 1)
            payout = size + pnl
            if pnl < 0:
                self.losses += 1
            else:
                self.wins += 1
        
        # Add back to balance
        self.balance += payout
        self.realized_pnl += pnl
        
        # Update position
        position['status'] = 'closed'
        position['exit_price'] = exit_price
        position['pnl'] = pnl
        position['close_timestamp'] = datetime.now().isoformat()
        
        del self.positions[position_key]
        
        self._save_state()
        
        result = "✅ WIN" if pnl > 0 else "❌ LOSS"
        
        self.logger.info("")
        self.logger.info("⚡" + "=" * 68)
        self.logger.info(f"   {result}: {outcome}")
        self.logger.info(f"   Market: {title}...")
        self.logger.info(f"   Entry: {entry_price:.3f} → Exit: {exit_price:.3f}")
        self.logger.info(f"   P&L: ${pnl:+.2f}")
        self.logger.info(f"   Balance: ${self.balance:.2f}")
        self.logger.info("=" * 70)
    
    def print_summary(self):
        """Print trading summary."""
        self.logger.info("")
        self.logger.info("=" * 70)
        self.logger.info("         📊 FAST COPY TRADING SUMMARY")
        self.logger.info("=" * 70)
        self.logger.info(f"   Starting Balance: ${self.initial_balance:.2f}")
        self.logger.info(f"   Current Balance:  ${self.balance:.2f}")
        self.logger.info(f"   Open Positions:   {len(self.positions)}")
        self.logger.info(f"   Total Trades:     {self.total_trades}")
        self.logger.info(f"   Wins/Losses:      {self.wins}/{self.losses}")
        if self.wins + self.losses > 0:
            self.logger.info(f"   Win Rate:         {self.wins/(self.wins+self.losses)*100:.1f}%")
        self.logger.info(f"   Realized P&L:     ${self.realized_pnl:+.2f}")
        net = self.balance - self.initial_balance
        self.logger.info(f"   Net P&L:          ${net:+.2f}")
        self.logger.info("=" * 70)


async def main():
    # gabagool22's wallet
    GABAGOOL_WALLET = "0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d"
    
    trader = FastCopyTrader(wallet=GABAGOOL_WALLET, balance=200.0)
    
    import signal
    def handler(sig, frame):
        print("\n\nShutting down...")
        asyncio.create_task(trader.stop())
    
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
    
    try:
        await trader.start()
    except KeyboardInterrupt:
        pass
    finally:
        await trader.stop()


if __name__ == "__main__":
    asyncio.run(main())

