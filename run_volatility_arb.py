#!/usr/bin/env python3
"""
VOLATILITY ARBITRAGE BOT - Based on Finbold $63 → $131K Strategy

Strategy:
1. Enter BOTH sides early when market opens (high spreads)
2. As direction becomes clear, abandon losing side
3. When one side drops to $0.01-$0.03, buy heavily (30x potential)
4. Capture volatility swings, not directional bets

Starting balance: $200
"""

import asyncio
import aiohttp
import json
import signal
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field, asdict
import sys

sys.path.insert(0, str(Path(__file__).parent))

from src.data.live_btc_feed import LiveBTCFeed


@dataclass
class Position:
    market_id: str
    market_title: str
    side: str  # YES/UP or NO/DOWN
    qty: float
    entry_price: float
    entry_time: datetime
    status: str = "open"
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    pnl: Optional[float] = None


@dataclass
class Market:
    market_id: str
    title: str
    yes_price: float
    no_price: float
    first_seen: datetime
    our_yes_position: Optional[Position] = None
    our_no_position: Optional[Position] = None


class VolatilityArbBot:
    """
    Implements the market-making + volatility capture strategy.
    """
    
    POLYMARKET_API = "https://gamma-api.polymarket.com"
    
    def __init__(self, starting_balance: float = 200.0):
        self.balance = starting_balance
        self.initial_balance = starting_balance
        self.positions: Dict[str, Position] = {}
        self.closed_trades: List[Position] = []
        self.markets: Dict[str, Market] = {}
        self.seen_markets: Set[str] = set()
        
        # Strategy parameters
        self.initial_bet_size = 5.0  # Small initial bets on both sides
        self.heavy_buy_threshold = 0.05  # Buy heavily when price < $0.05
        self.heavy_buy_size = 20.0  # Larger bet on cheap side
        self.abandon_threshold = 0.15  # Abandon losing side when < $0.15
        self.take_profit_threshold = 0.85  # Take profit when > $0.85
        
        # Session
        self.session: Optional[aiohttp.ClientSession] = None
        self.btc_feed: Optional[LiveBTCFeed] = None
        self.running = False
        
        # Data persistence
        self.data_dir = Path("data/volatility_arb")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self._load_state()
    
    def _load_state(self):
        """Load previous state."""
        state_file = self.data_dir / "state.json"
        if state_file.exists():
            try:
                with open(state_file) as f:
                    state = json.load(f)
                    self.balance = state.get("balance", self.initial_balance)
                    self.seen_markets = set(state.get("seen_markets", []))
                    print(f"📂 Loaded state: Balance=${self.balance:.2f}")
            except Exception as e:
                print(f"⚠️ Could not load state: {e}")
    
    def _save_state(self):
        """Save current state."""
        state = {
            "balance": self.balance,
            "seen_markets": list(self.seen_markets)[-100:],
            "last_updated": datetime.now().isoformat()
        }
        with open(self.data_dir / "state.json", "w") as f:
            json.dump(state, f, indent=2)
    
    def _log_trade(self, position: Position):
        """Log trade to file."""
        with open(self.data_dir / "trades.jsonl", "a") as f:
            data = asdict(position)
            data["entry_time"] = position.entry_time.isoformat()
            if position.exit_time:
                data["exit_time"] = position.exit_time.isoformat()
            f.write(json.dumps(data) + "\n")
    
    async def start(self):
        """Start the bot."""
        print("=" * 70)
        print("  🎰 VOLATILITY ARBITRAGE BOT")
        print("=" * 70)
        print(f"  Strategy: Market-making + Volatility Capture")
        print(f"  Starting Balance: ${self.initial_balance:.2f}")
        print()
        print("  Parameters:")
        print(f"    Initial bet (both sides): ${self.initial_bet_size:.2f}")
        print(f"    Heavy buy threshold:      ${self.heavy_buy_threshold:.2f}")
        print(f"    Heavy buy size:           ${self.heavy_buy_size:.2f}")
        print(f"    Abandon threshold:        ${self.abandon_threshold:.2f}")
        print("=" * 70)
        print()
        
        self.session = aiohttp.ClientSession()
        self.btc_feed = LiveBTCFeed(buffer_size=60)
        await self.btc_feed.start()
        
        self.running = True
        
        # Start tasks
        scan_task = asyncio.create_task(self._scan_loop())
        manage_task = asyncio.create_task(self._manage_positions_loop())
        status_task = asyncio.create_task(self._status_loop())
        
        try:
            await asyncio.gather(scan_task, manage_task, status_task)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()
    
    async def stop(self):
        """Stop the bot."""
        self.running = False
        self._save_state()
        
        if self.btc_feed:
            await self.btc_feed.stop()
        if self.session:
            await self.session.close()
        
        self._print_summary()
    
    async def _scan_loop(self):
        """Scan for new BTC/ETH 15-min markets."""
        while self.running:
            try:
                await self._scan_markets()
            except Exception as e:
                print(f"⚠️ Scan error: {e}")
            await asyncio.sleep(5)  # Scan every 5 seconds
    
    async def _manage_positions_loop(self):
        """Manage existing positions."""
        while self.running:
            try:
                await self._manage_positions()
            except Exception as e:
                print(f"⚠️ Position management error: {e}")
            await asyncio.sleep(3)  # Check every 3 seconds
    
    async def _status_loop(self):
        """Print status periodically."""
        while self.running:
            await asyncio.sleep(60)
            self._print_status()
    
    async def _scan_markets(self):
        """Scan for new crypto 15-min markets."""
        # Search for active BTC/ETH markets
        try:
            url = f"{self.POLYMARKET_API}/markets"
            params = {
                "active": "true",
                "closed": "false",
                "limit": 50
            }
            
            async with self.session.get(url, params=params, timeout=10) as resp:
                if resp.status != 200:
                    return
                
                markets = await resp.json()
                
                for market in markets:
                    question = market.get("question", "").lower()
                    market_id = market.get("conditionId", "")
                    
                    # Filter for BTC/ETH 15-min markets
                    is_crypto = any(x in question for x in ["bitcoin", "btc", "ethereum", "eth"])
                    is_15min = "15" in question or "up or down" in question
                    
                    if is_crypto and is_15min and market_id not in self.seen_markets:
                        await self._handle_new_market(market)
                        
        except Exception as e:
            pass  # Silent fail, will retry
    
    async def _handle_new_market(self, market: dict):
        """Handle a newly discovered market - enter both sides."""
        market_id = market.get("conditionId", "")
        title = market.get("question", "Unknown")
        
        # Get current prices
        outcomes = market.get("outcomes", [])
        tokens = market.get("tokens", [])
        
        if len(tokens) < 2:
            return
        
        yes_price = float(tokens[0].get("price", 0.5))
        no_price = float(tokens[1].get("price", 0.5))
        
        # Only enter if spread is interesting (both sides have value)
        if yes_price < 0.10 or no_price < 0.10:
            return  # Skip if one side is too cheap (market already decided)
        
        if yes_price > 0.90 or no_price > 0.90:
            return  # Skip if one side is too expensive
        
        # Check if we have enough balance
        total_cost = self.initial_bet_size * (yes_price + no_price)
        if total_cost > self.balance:
            return
        
        self.seen_markets.add(market_id)
        now = datetime.now()
        
        # Enter YES side
        yes_qty = self.initial_bet_size / yes_price
        yes_position = Position(
            market_id=market_id,
            market_title=title,
            side="YES",
            qty=yes_qty,
            entry_price=yes_price,
            entry_time=now
        )
        self.positions[f"{market_id}_YES"] = yes_position
        self.balance -= self.initial_bet_size
        self._log_trade(yes_position)
        
        # Enter NO side
        no_qty = self.initial_bet_size / no_price
        no_position = Position(
            market_id=market_id,
            market_title=title,
            side="NO",
            qty=no_qty,
            entry_price=no_price,
            entry_time=now
        )
        self.positions[f"{market_id}_NO"] = no_position
        self.balance -= self.initial_bet_size
        self._log_trade(no_position)
        
        # Track market
        self.markets[market_id] = Market(
            market_id=market_id,
            title=title,
            yes_price=yes_price,
            no_price=no_price,
            first_seen=now,
            our_yes_position=yes_position,
            our_no_position=no_position
        )
        
        print(f"\n🎯 NEW MARKET: {title[:50]}...")
        print(f"   YES: {yes_qty:.1f} @ ${yes_price:.2f} | NO: {no_qty:.1f} @ ${no_price:.2f}")
        print(f"   Total invested: ${total_cost:.2f} | Balance: ${self.balance:.2f}")
        
        self._save_state()
    
    async def _manage_positions(self):
        """Manage existing positions - key strategy logic."""
        for market_id, market in list(self.markets.items()):
            # Get current prices
            try:
                url = f"{self.POLYMARKET_API}/markets/{market_id}"
                async with self.session.get(url, timeout=5) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    
                tokens = data.get("tokens", [])
                if len(tokens) < 2:
                    continue
                
                current_yes = float(tokens[0].get("price", 0.5))
                current_no = float(tokens[1].get("price", 0.5))
                
                market.yes_price = current_yes
                market.no_price = current_no
                
                # Strategy logic
                await self._apply_strategy(market, current_yes, current_no)
                
            except Exception as e:
                continue
    
    async def _apply_strategy(self, market: Market, yes_price: float, no_price: float):
        """Apply the volatility capture strategy."""
        yes_key = f"{market.market_id}_YES"
        no_key = f"{market.market_id}_NO"
        
        # 1. HEAVY BUY - If one side drops below threshold, buy more
        if yes_price < self.heavy_buy_threshold and yes_key in self.positions:
            pos = self.positions[yes_key]
            if self.balance >= self.heavy_buy_size * yes_price:
                # Add to position
                add_qty = self.heavy_buy_size / yes_price
                pos.qty += add_qty
                self.balance -= self.heavy_buy_size * yes_price
                print(f"\n💰 HEAVY BUY YES: {market.title[:40]}... @ ${yes_price:.3f}")
                print(f"   Added {add_qty:.1f} shares | Total: {pos.qty:.1f}")
        
        if no_price < self.heavy_buy_threshold and no_key in self.positions:
            pos = self.positions[no_key]
            if self.balance >= self.heavy_buy_size * no_price:
                add_qty = self.heavy_buy_size / no_price
                pos.qty += add_qty
                self.balance -= self.heavy_buy_size * no_price
                print(f"\n💰 HEAVY BUY NO: {market.title[:40]}... @ ${no_price:.3f}")
                print(f"   Added {add_qty:.1f} shares | Total: {pos.qty:.1f}")
        
        # 2. ABANDON LOSING SIDE - If one side is very cheap, sell it
        if yes_price < self.abandon_threshold and yes_key in self.positions:
            pos = self.positions[yes_key]
            pnl = pos.qty * yes_price - (pos.qty * pos.entry_price)
            pos.exit_price = yes_price
            pos.exit_time = datetime.now()
            pos.pnl = pnl
            pos.status = "closed"
            self.balance += pos.qty * yes_price
            self.closed_trades.append(pos)
            del self.positions[yes_key]
            self._log_trade(pos)
            print(f"\n🚫 ABANDON YES: {market.title[:40]}... @ ${yes_price:.3f}")
            print(f"   P&L: ${pnl:+.2f}")
        
        if no_price < self.abandon_threshold and no_key in self.positions:
            pos = self.positions[no_key]
            pnl = pos.qty * no_price - (pos.qty * pos.entry_price)
            pos.exit_price = no_price
            pos.exit_time = datetime.now()
            pos.pnl = pnl
            pos.status = "closed"
            self.balance += pos.qty * no_price
            self.closed_trades.append(pos)
            del self.positions[no_key]
            self._log_trade(pos)
            print(f"\n🚫 ABANDON NO: {market.title[:40]}... @ ${no_price:.3f}")
            print(f"   P&L: ${pnl:+.2f}")
        
        # 3. TAKE PROFIT - If one side is very high, sell it
        if yes_price > self.take_profit_threshold and yes_key in self.positions:
            pos = self.positions[yes_key]
            pnl = pos.qty * yes_price - (pos.qty * pos.entry_price)
            pos.exit_price = yes_price
            pos.exit_time = datetime.now()
            pos.pnl = pnl
            pos.status = "closed"
            self.balance += pos.qty * yes_price
            self.closed_trades.append(pos)
            del self.positions[yes_key]
            self._log_trade(pos)
            print(f"\n✅ TAKE PROFIT YES: {market.title[:40]}... @ ${yes_price:.3f}")
            print(f"   P&L: ${pnl:+.2f}")
        
        if no_price > self.take_profit_threshold and no_key in self.positions:
            pos = self.positions[no_key]
            pnl = pos.qty * no_price - (pos.qty * pos.entry_price)
            pos.exit_price = no_price
            pos.exit_time = datetime.now()
            pos.pnl = pnl
            pos.status = "closed"
            self.balance += pos.qty * no_price
            self.closed_trades.append(pos)
            del self.positions[no_key]
            self._log_trade(pos)
            print(f"\n✅ TAKE PROFIT NO: {market.title[:40]}... @ ${no_price:.3f}")
            print(f"   P&L: ${pnl:+.2f}")
    
    def _print_status(self):
        """Print current status."""
        now = datetime.now().strftime("%H:%M:%S")
        btc = self.btc_feed.get_current_price() if self.btc_feed else 0
        realized_pnl = sum(t.pnl or 0 for t in self.closed_trades)
        
        print(f"\n{'─' * 70}")
        print(f"📊 VOLATILITY ARB @ {now} | BTC: ${btc:,.2f}")
        print(f"{'─' * 70}")
        print(f"  Balance: ${self.balance:.2f} | Open: {len(self.positions)} | "
              f"Closed: {len(self.closed_trades)} | P&L: ${realized_pnl:+.2f}")
        print(f"{'─' * 70}")
    
    def _print_summary(self):
        """Print final summary."""
        realized_pnl = sum(t.pnl or 0 for t in self.closed_trades)
        wins = len([t for t in self.closed_trades if (t.pnl or 0) > 0])
        losses = len([t for t in self.closed_trades if (t.pnl or 0) <= 0])
        
        print("\n" + "=" * 70)
        print("  📈 VOLATILITY ARB - FINAL SUMMARY")
        print("=" * 70)
        print(f"  Starting:    ${self.initial_balance:.2f}")
        print(f"  Final:       ${self.balance:.2f}")
        print(f"  Realized:    ${realized_pnl:+.2f}")
        print(f"  Win/Loss:    {wins}W / {losses}L")
        print(f"  Trades:      {len(self.closed_trades)}")
        print("=" * 70)


async def main():
    bot = VolatilityArbBot(starting_balance=200.0)
    
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(bot.stop()))
    
    await bot.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nShutdown requested...")

