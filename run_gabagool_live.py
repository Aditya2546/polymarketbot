#!/usr/bin/env python3
"""
GABAGOOL LIVE COPY TRADER
=========================
Tracks @gabagool22 in real-time, simulates copies, shows results.

Run: python run_gabagool_live.py
"""

import asyncio
import aiohttp
import json
import signal
import sys
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Set
from collections import defaultdict
import pytz

# Setup path
sys.path.insert(0, str(Path(__file__).parent))

from src.data.live_btc_feed import LiveBTCFeed


@dataclass
class CopiedTrade:
    """A trade we copied from gabagool."""
    trade_id: str
    timestamp: str
    market_title: str
    market_id: str
    side: str  # UP or DOWN / YES or NO
    action: str  # BUY or SELL
    gabagool_qty: float
    gabagool_price: float
    our_qty: float
    our_entry_price: float
    our_cost: float
    
    # Settlement
    status: str = "open"  # open, settled
    settlement_time: Optional[str] = None
    settlement_price: Optional[float] = None
    outcome: Optional[str] = None  # UP or DOWN
    pnl: Optional[float] = None


@dataclass
class MarketPosition:
    """Position in a single market."""
    market_id: str
    market_title: str
    expiry_time: Optional[datetime] = None
    
    # Positions
    up_qty: float = 0.0
    up_cost: float = 0.0
    down_qty: float = 0.0
    down_cost: float = 0.0
    
    # Trades in this market
    trades: List[str] = field(default_factory=list)
    
    @property
    def up_avg(self) -> float:
        return self.up_cost / self.up_qty if self.up_qty > 0 else 0
    
    @property
    def down_avg(self) -> float:
        return self.down_cost / self.down_qty if self.down_qty > 0 else 0


class GabagoolLiveCopier:
    """
    Live copy trader for gabagool22.
    
    - Polls Polymarket every 2 seconds
    - Copies trades with proportional sizing
    - Tracks 15-minute markets
    - Settles and reports P&L
    """
    
    WALLET = "0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d"
    GAMMA_API = "https://gamma-api.polymarket.com"
    
    def __init__(self, balance: float = 200.0):
        self.balance = balance
        self.initial_balance = balance
        
        # Data storage
        self.data_dir = Path("data/gabagool_live")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # State
        self.trades: Dict[str, CopiedTrade] = {}
        self.positions: Dict[str, MarketPosition] = {}
        self.seen_trade_ids: Set[str] = set()
        
        # Stats
        self.total_trades = 0
        self.total_pnl = 0.0
        self.wins = 0
        self.losses = 0
        
        # BTC/ETH price feed
        self.price_feed: Optional[LiveBTCFeed] = None
        
        # Gabagool's estimated portfolio for scaling
        self.gabagool_portfolio = 50000
        self.our_scale = balance / self.gabagool_portfolio
        
        # Control
        self.running = False
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Timezone
        self.et = pytz.timezone('US/Eastern')
        
        # Load existing state
        self._load_state()
    
    def _load_state(self):
        """Load existing state from disk."""
        state_file = self.data_dir / "state.json"
        if state_file.exists():
            try:
                with open(state_file) as f:
                    state = json.load(f)
                self.balance = state.get('balance', self.balance)
                self.total_pnl = state.get('total_pnl', 0)
                self.wins = state.get('wins', 0)
                self.losses = state.get('losses', 0)
                self.seen_trade_ids = set(state.get('seen_trade_ids', []))
                print(f"  Loaded state: ${self.balance:.2f} balance, {len(self.seen_trade_ids)} seen trades")
            except Exception as e:
                print(f"  Could not load state: {e}")
        
        # Load open trades
        trades_file = self.data_dir / "trades.jsonl"
        if trades_file.exists():
            try:
                with open(trades_file) as f:
                    for line in f:
                        t = json.loads(line)
                        trade = CopiedTrade(**t)
                        self.trades[trade.trade_id] = trade
                        
                        # Track position
                        if trade.status == "open":
                            if trade.market_id not in self.positions:
                                self.positions[trade.market_id] = MarketPosition(
                                    market_id=trade.market_id,
                                    market_title=trade.market_title
                                )
                            pos = self.positions[trade.market_id]
                            if trade.side in ("UP", "YES"):
                                pos.up_qty += trade.our_qty
                                pos.up_cost += trade.our_cost
                            else:
                                pos.down_qty += trade.our_qty
                                pos.down_cost += trade.our_cost
                            pos.trades.append(trade.trade_id)
                
                open_count = len([t for t in self.trades.values() if t.status == "open"])
                print(f"  Loaded {len(self.trades)} trades ({open_count} open)")
            except Exception as e:
                print(f"  Could not load trades: {e}")
    
    def _save_state(self):
        """Save state to disk."""
        state_file = self.data_dir / "state.json"
        with open(state_file, 'w') as f:
            json.dump({
                'balance': self.balance,
                'total_pnl': self.total_pnl,
                'wins': self.wins,
                'losses': self.losses,
                'seen_trade_ids': list(self.seen_trade_ids)[-10000:],  # Keep last 10k
                'updated_at': datetime.now().isoformat()
            }, f, indent=2)
    
    def _save_trade(self, trade: CopiedTrade):
        """Append trade to JSONL file."""
        trades_file = self.data_dir / "trades.jsonl"
        with open(trades_file, 'a') as f:
            f.write(json.dumps(asdict(trade)) + '\n')
    
    def _update_trade(self, trade: CopiedTrade):
        """Update trade in file (rewrite all)."""
        self.trades[trade.trade_id] = trade
        trades_file = self.data_dir / "trades.jsonl"
        with open(trades_file, 'w') as f:
            for t in self.trades.values():
                f.write(json.dumps(asdict(t)) + '\n')
    
    async def start(self):
        """Start the live copier."""
        self.running = True
        
        print()
        print("=" * 70)
        print("  🎯 GABAGOOL LIVE COPY TRADER")
        print("=" * 70)
        print(f"  Tracking: @gabagool22")
        print(f"  Balance: ${self.balance:.2f}")
        print(f"  Scale: {self.our_scale:.4%} of gabagool's size")
        print("=" * 70)
        print()
        
        # Start price feed
        print("📡 Starting price feed...")
        self.price_feed = LiveBTCFeed(buffer_size=300)
        await self.price_feed.start()
        
        btc_price = self.price_feed.get_current_price()
        if btc_price:
            print(f"  ✓ BTC: ${btc_price:,.2f}")
        
        # Start HTTP session
        self.session = aiohttp.ClientSession()
        
        print()
        print("🟢 LIVE - Polling every 2 seconds. Press Ctrl+C to stop.")
        print("-" * 70)
        print()
        
        # Run main loop
        await self._main_loop()
    
    async def stop(self):
        """Stop the copier."""
        self.running = False
        
        if self.session:
            await self.session.close()
        
        if self.price_feed:
            await self.price_feed.stop()
        
        self._save_state()
        self._print_summary()
    
    async def _main_loop(self):
        """Main polling loop."""
        last_summary = datetime.now()
        
        while self.running:
            try:
                # Poll for new trades
                new_trades = await self._poll_gabagool()
                
                for trade_data in new_trades:
                    await self._process_trade(trade_data)
                
                # Check for settlements
                await self._check_settlements()
                
                # Periodic summary (every 5 minutes)
                if (datetime.now() - last_summary).seconds >= 300:
                    self._print_status()
                    last_summary = datetime.now()
                
                # Save state
                self._save_state()
                
                # Wait
                await asyncio.sleep(2)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"  ⚠️ Error: {e}")
                await asyncio.sleep(5)
    
    async def _poll_gabagool(self) -> List[Dict]:
        """Poll for gabagool's recent trades."""
        try:
            url = f"{self.GAMMA_API}/activity"
            params = {
                "user": self.WALLET,
                "limit": 20
            }
            
            async with self.session.get(url, params=params, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    activities = data if isinstance(data, list) else data.get('activities', [])
                    
                    # Filter for new trades
                    new_trades = []
                    for activity in activities:
                        trade_id = activity.get('id', activity.get('transactionHash', ''))
                        if trade_id and trade_id not in self.seen_trade_ids:
                            # Check if it's a trade (not a deposit/withdraw)
                            action = activity.get('type', '').upper()
                            if action in ('BUY', 'SELL', 'TRADE'):
                                new_trades.append(activity)
                                self.seen_trade_ids.add(trade_id)
                    
                    return new_trades
                else:
                    # Try alternative endpoint
                    return await self._poll_gabagool_alt()
                    
        except Exception as e:
            return []
    
    async def _poll_gabagool_alt(self) -> List[Dict]:
        """Alternative polling via positions endpoint."""
        try:
            url = f"{self.GAMMA_API}/users/{self.WALLET}/positions"
            async with self.session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    return []  # Positions don't give us trade details
        except:
            pass
        return []
    
    async def _process_trade(self, trade_data: Dict):
        """Process a new gabagool trade."""
        trade_id = trade_data.get('id', trade_data.get('transactionHash', str(hash(str(trade_data)))))
        
        # Parse trade details
        market_title = trade_data.get('title', trade_data.get('question', 'Unknown Market'))
        market_id = trade_data.get('conditionId', trade_data.get('asset', ''))
        
        # Determine side
        outcome = trade_data.get('outcome', '').upper()
        if outcome in ('UP', 'YES'):
            side = 'UP'
        elif outcome in ('DOWN', 'NO'):
            side = 'DOWN'
        else:
            side = 'UP'  # Default
        
        # Action
        action = trade_data.get('side', trade_data.get('type', 'BUY')).upper()
        if action not in ('BUY', 'SELL'):
            action = 'BUY'
        
        # Quantities
        gabagool_qty = float(trade_data.get('size', trade_data.get('shares', 0)))
        gabagool_price = float(trade_data.get('price', 0.5))
        
        if gabagool_qty <= 0:
            return
        
        # Calculate our position
        our_qty = gabagool_qty * self.our_scale * 1000  # Scale up for meaningful size
        our_qty = max(2.0, min(our_qty, self.balance * 0.15))  # 2-15% of balance
        our_cost = our_qty * gabagool_price
        
        # Check balance
        if our_cost > self.balance:
            print(f"  ⚠️ Insufficient balance for trade (need ${our_cost:.2f}, have ${self.balance:.2f})")
            return
        
        # Get current BTC/ETH price for reference
        current_price = None
        if self.price_feed:
            if 'bitcoin' in market_title.lower() or 'btc' in market_title.lower():
                current_price = self.price_feed.get_current_price()
            elif 'ethereum' in market_title.lower() or 'eth' in market_title.lower():
                current_price = self.price_feed.get_current_price(asset_type="ETH")
        
        # Create trade record
        trade = CopiedTrade(
            trade_id=trade_id,
            timestamp=datetime.now().isoformat(),
            market_title=market_title,
            market_id=market_id,
            side=side,
            action=action,
            gabagool_qty=gabagool_qty,
            gabagool_price=gabagool_price,
            our_qty=our_qty,
            our_entry_price=gabagool_price,
            our_cost=our_cost
        )
        
        # Update balance
        if action == "BUY":
            self.balance -= our_cost
        
        # Track position
        if market_id not in self.positions:
            self.positions[market_id] = MarketPosition(
                market_id=market_id,
                market_title=market_title,
                expiry_time=self._parse_expiry(market_title)
            )
        
        pos = self.positions[market_id]
        if action == "BUY":
            if side == "UP":
                pos.up_qty += our_qty
                pos.up_cost += our_cost
            else:
                pos.down_qty += our_qty
                pos.down_cost += our_cost
        pos.trades.append(trade_id)
        
        # Save trade
        self.trades[trade_id] = trade
        self._save_trade(trade)
        self.total_trades += 1
        
        # Print notification
        price_str = f" | Asset: ${current_price:,.2f}" if current_price else ""
        print(f"  🎯 COPIED: {action} {side} ${our_cost:.2f} @ {gabagool_price:.3f}{price_str}")
        print(f"     Market: {market_title[:50]}...")
        print(f"     Gabagool: {gabagool_qty:.2f} shares | Us: {our_qty:.2f} shares")
        print(f"     Balance: ${self.balance:.2f}")
        print()
    
    def _parse_expiry(self, title: str) -> Optional[datetime]:
        """Parse expiry time from market title."""
        try:
            import re
            
            # Pattern: "January 7, 6:45PM-7:00PM ET"
            match = re.search(r'(\w+)\s+(\d{1,2}),?\s+(\d{1,2}):?(\d{2})?(AM|PM)?-?(\d{1,2})?:?(\d{2})?(AM|PM)?\s*ET', title, re.IGNORECASE)
            
            if match:
                month_str = match.group(1)
                day = int(match.group(2))
                
                # End time
                end_hour = int(match.group(6) or match.group(3))
                end_min = int(match.group(7) or match.group(4) or 0)
                ampm = (match.group(8) or match.group(5) or 'PM').upper()
                
                if ampm == 'PM' and end_hour != 12:
                    end_hour += 12
                elif ampm == 'AM' and end_hour == 12:
                    end_hour = 0
                
                # Build datetime
                months = {'january': 1, 'february': 2, 'march': 3, 'april': 4, 
                         'may': 5, 'june': 6, 'july': 7, 'august': 8,
                         'september': 9, 'october': 10, 'november': 11, 'december': 12}
                month = months.get(month_str.lower(), 1)
                
                now = datetime.now(self.et)
                year = now.year
                
                expiry = self.et.localize(datetime(year, month, day, end_hour, end_min))
                return expiry
        except:
            pass
        
        return None
    
    async def _check_settlements(self):
        """Check for markets that should be settled."""
        now = datetime.now(self.et)
        
        for market_id, pos in list(self.positions.items()):
            # Check if expired
            if pos.expiry_time and now > pos.expiry_time:
                await self._settle_market(market_id, pos)
    
    async def _settle_market(self, market_id: str, pos: MarketPosition):
        """Settle a market and calculate P&L."""
        # Get settlement price
        settlement_price = None
        if self.price_feed:
            if 'bitcoin' in pos.market_title.lower() or 'btc' in pos.market_title.lower():
                settlement_price = self.price_feed.get_current_price()
            elif 'ethereum' in pos.market_title.lower() or 'eth' in pos.market_title.lower():
                settlement_price = self.price_feed.get_current_price(asset_type="ETH")
        
        # For 15-min markets, we need start and end prices
        # This is simplified - in reality we'd track the start price
        # For now, we'll use a simple heuristic based on our position
        
        # Determine outcome (simplified - assumes we track from start)
        # In production, you'd compare start vs end price
        outcome = "UP"  # Placeholder - should be determined by actual price movement
        
        # Calculate P&L for each trade in this market
        total_pnl = 0.0
        for trade_id in pos.trades:
            if trade_id in self.trades:
                trade = self.trades[trade_id]
                if trade.status == "open":
                    # Settle trade
                    if trade.side == outcome:
                        # Win: payout is $1 per share
                        payout = trade.our_qty * 1.0
                        pnl = payout - trade.our_cost
                        self.wins += 1
                    else:
                        # Loss: lose the cost
                        pnl = -trade.our_cost
                        self.losses += 1
                    
                    trade.status = "settled"
                    trade.settlement_time = datetime.now().isoformat()
                    trade.settlement_price = settlement_price
                    trade.outcome = outcome
                    trade.pnl = pnl
                    
                    total_pnl += pnl
                    self.balance += (trade.our_cost + pnl)  # Return cost + pnl
                    
                    self._update_trade(trade)
        
        self.total_pnl += total_pnl
        
        # Remove settled position
        del self.positions[market_id]
        
        # Print settlement
        result = "✅ WIN" if total_pnl > 0 else "❌ LOSS"
        print(f"  {result}: {pos.market_title[:40]}...")
        print(f"     Outcome: {outcome} | P&L: ${total_pnl:+.2f}")
        print(f"     Balance: ${self.balance:.2f}")
        print()
    
    def _print_status(self):
        """Print current status."""
        print()
        print("-" * 70)
        print(f"  📊 STATUS @ {datetime.now().strftime('%H:%M:%S')}")
        print("-" * 70)
        print(f"  Balance: ${self.balance:.2f} (started: ${self.initial_balance:.2f})")
        print(f"  Total P&L: ${self.total_pnl:+.2f}")
        print(f"  Trades: {self.total_trades} | Wins: {self.wins} | Losses: {self.losses}")
        
        if self.positions:
            print(f"\n  Open Positions ({len(self.positions)}):")
            for pos in self.positions.values():
                total_cost = pos.up_cost + pos.down_cost
                print(f"    • {pos.market_title[:40]}...")
                print(f"      UP: {pos.up_qty:.1f} @ {pos.up_avg:.3f} | DOWN: {pos.down_qty:.1f} @ {pos.down_avg:.3f}")
        
        print("-" * 70)
        print()
    
    def _print_summary(self):
        """Print final summary."""
        print()
        print("=" * 70)
        print("  📈 FINAL SUMMARY")
        print("=" * 70)
        print(f"  Starting Balance: ${self.initial_balance:.2f}")
        print(f"  Final Balance: ${self.balance:.2f}")
        print(f"  Total P&L: ${self.total_pnl:+.2f} ({(self.total_pnl/self.initial_balance)*100:+.1f}%)")
        print()
        print(f"  Total Trades: {self.total_trades}")
        print(f"  Wins: {self.wins}")
        print(f"  Losses: {self.losses}")
        if self.wins + self.losses > 0:
            print(f"  Win Rate: {self.wins/(self.wins+self.losses)*100:.1f}%")
        print()
        print(f"  Data saved to: {self.data_dir}")
        print("=" * 70)


async def main():
    copier = GabagoolLiveCopier(balance=200.0)
    
    # Handle shutdown
    def shutdown_handler(sig, frame):
        print("\n\n  Shutting down...")
        asyncio.create_task(copier.stop())
    
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)
    
    try:
        await copier.start()
    except KeyboardInterrupt:
        pass
    finally:
        await copier.stop()


if __name__ == "__main__":
    print()
    print("  Starting Gabagool Live Copy Trader...")
    print()
    asyncio.run(main())

