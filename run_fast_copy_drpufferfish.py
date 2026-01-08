#!/usr/bin/env python3
"""
FAST COPY TRADER for @DrPufferfish
FILTERED: Only same-day sports bets (NBA games, etc.)
Skips long-term bets like "Win the Finals"
"""

import asyncio
import aiohttp
import json
from datetime import datetime
from pathlib import Path
import sys
import re

sys.path.insert(0, str(Path(__file__).parent))
from src.logger import setup_logging, StructuredLogger

class FastCopyTrader:
    def __init__(self, wallet: str, name: str, balance: float = 200.0):
        setup_logging(level="INFO", log_format="text")
        self.logger = StructuredLogger(__name__)
        self.wallet = wallet
        self.name = name
        self.balance = balance
        self.initial_balance = balance
        
        self.data_dir = Path(f"data/fast_copy_{name.lower()}")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.trades_file = self.data_dir / "trades.jsonl"
        self.perf_file = self.data_dir / "performance.json"
        
        self.seen_trades = set()
        self.positions = {}
        self.total_trades = 0
        self.wins = 0
        self.losses = 0
        self.realized_pnl = 0
        self.portfolio_value = 500000
        self.our_scale = balance / self.portfolio_value
        self.running = False
        self.poll_interval = 2
        self._load_state()
    
    def _load_state(self):
        if self.perf_file.exists():
            with open(self.perf_file) as f:
                state = json.load(f)
                self.balance = state.get('balance', self.balance)
                self.wins = state.get('wins', 0)
                self.losses = state.get('losses', 0)
                self.realized_pnl = state.get('realized_pnl', 0)
                self.seen_trades = set(state.get('seen_trades', []))
        if self.trades_file.exists():
            with open(self.trades_file) as f:
                for line in f:
                    trade = json.loads(line)
                    if trade.get('status') == 'open':
                        key = f"{trade['market_id']}_{trade['outcome']}"
                        self.positions[key] = trade
    
    def _save_state(self):
        state = {
            'balance': self.balance, 'wins': self.wins, 'losses': self.losses,
            'realized_pnl': self.realized_pnl,
            'seen_trades': list(self.seen_trades)[-1000:],
            'last_update': datetime.now().isoformat()
        }
        with open(self.perf_file, 'w') as f:
            json.dump(state, f, indent=2)
    
    def is_same_day_trade(self, title: str) -> bool:
        """
        Check if this is a same-day trade (not long-term).
        Returns True for: "Bulls vs. Pistons", "Lakers (-6.5)", game spreads
        Returns False for: "Win the Finals", "Win the Championship", season bets
        """
        title_lower = title.lower()
        
        # SKIP these long-term bets
        long_term_keywords = [
            'win the', 'finals', 'championship', 'playoff', 'season',
            'mvp', 'award', 'win 202', 'make the', 'reach the',
            'super bowl', 'world series', 'stanley cup'
        ]
        
        for keyword in long_term_keywords:
            if keyword in title_lower:
                return False
        
        # ALLOW these same-day patterns
        same_day_patterns = [
            r'vs\.', r'vs ', r'\(-?\d+\.?\d*\)',  # "vs." or spread like "(-6.5)"
            r'january \d+', r'jan \d+',  # Date in title
            r'\d{4}-\d{2}-\d{2}',  # Date format
            'tonight', 'today', 'game \d',
            'bulls', 'lakers', 'celtics', 'warriors', 'heat', 'nets',  # NBA teams
            'spread:', 'over/under', 'total points'
        ]
        
        for pattern in same_day_patterns:
            if re.search(pattern, title_lower):
                return True
        
        # Default: skip if unsure
        return False
    
    async def start(self):
        self.running = True
        self.logger.info("=" * 70)
        self.logger.info(f"⚡ FAST COPY - @{self.name} (SAME-DAY ONLY)")
        self.logger.info("=" * 70)
        self.logger.info(f"   Wallet: {self.wallet}")
        self.logger.info(f"   Balance: ${self.balance:.2f}")
        self.logger.info(f"   Filter: Same-day sports bets only")
        self.logger.info("=" * 70)
        self.logger.info("🟢 LIVE - Watching for same-day trades...")
        await self.poll_loop()
    
    async def stop(self):
        self.running = False
        self._save_state()
    
    async def poll_loop(self):
        async with aiohttp.ClientSession() as session:
            while self.running:
                try:
                    await self.check_for_trades(session)
                    await asyncio.sleep(self.poll_interval)
                except Exception as e:
                    self.logger.error(f"Error: {e}")
                    await asyncio.sleep(5)
    
    async def check_for_trades(self, session):
        url = f"https://data-api.polymarket.com/trades?user={self.wallet}&limit=20"
        try:
            async with session.get(url, timeout=5) as resp:
                if resp.status != 200: return
                trades = await resp.json()
                trades.sort(key=lambda x: x.get('timestamp', 0))
                for trade in trades:
                    trade_id = f"{trade.get('timestamp')}_{trade.get('conditionId')}_{trade.get('side')}"
                    if trade_id in self.seen_trades: continue
                    self.seen_trades.add(trade_id)
                    
                    # Filter for same-day trades only
                    title = trade.get('title', '')
                    if not self.is_same_day_trade(title):
                        self.logger.debug(f"⏭️ Skipped (long-term): {title[:40]}...")
                        continue
                    
                    await self.process_trade(trade)
        except: pass
    
    async def process_trade(self, trade):
        side = trade.get('side', '').upper()
        outcome = trade.get('outcome', 'Unknown')
        title = trade.get('title', 'Unknown')[:45]
        market_id = trade.get('conditionId', '')
        price = float(trade.get('price', 0.5))
        size = float(trade.get('size', 0))
        value = size * price
        position_key = f"{market_id}_{outcome}"
        
        if side == "BUY":
            our_size = min(value * self.our_scale, self.balance * 0.15, 15.0)
            our_size = max(our_size, 2.0)
            if our_size > self.balance: return
            self.balance -= our_size
            position = {
                'timestamp': datetime.now().isoformat(),
                'market_id': market_id, 'market_title': title,
                'outcome': outcome, 'side': 'BUY',
                'entry_price': price, 'size': our_size, 'status': 'open'
            }
            self.positions[position_key] = position
            self.total_trades += 1
            with open(self.trades_file, 'a') as f:
                f.write(json.dumps(position) + '\n')
            self._save_state()
            self.logger.info(f"⚡ OPENED: {outcome} - {title}... | ${our_size:.2f} @ {price:.3f}")
            
        elif side == "SELL" and position_key in self.positions:
            position = self.positions[position_key]
            entry_price = position['entry_price']
            size = position['size']
            pnl = size * (price / entry_price - 1)
            payout = size + pnl
            self.balance += payout
            self.realized_pnl += pnl
            if pnl > 0: self.wins += 1
            else: self.losses += 1
            del self.positions[position_key]
            self._save_state()
            result = "✅" if pnl > 0 else "❌"
            self.logger.info(f"{result} CLOSED: {outcome} | P&L: ${pnl:+.2f} | Bal: ${self.balance:.2f}")

async def main():
    trader = FastCopyTrader(
        wallet="0xdb27bf2ac5d428a9c63dbc914611036855a6c56e",
        name="DrPufferfish",
        balance=200.0
    )
    import signal
    def handler(s, f): asyncio.create_task(trader.stop())
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)
    try: await trader.start()
    except: pass
    finally: await trader.stop()

if __name__ == "__main__":
    asyncio.run(main())
