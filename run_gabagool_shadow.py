#!/usr/bin/env python3
"""
GABAGOOL LIVE SHADOW COPY - Dual Simulation

Runs continuously, copying gabagool's trades on:
- Polymarket (exact copy baseline)
- Kalshi (realistic orderbook simulation)

Starting balance: $200 each
Results shown every 15 minutes as markets settle.
"""

import asyncio
import json
import aiohttp
import signal
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field, asdict
from collections import defaultdict
import hashlib

# Add project root
sys.path.insert(0, str(Path(__file__).parent))

from src.data.live_btc_feed import LiveBTCFeed


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class Position:
    """A position in a market."""
    market_id: str
    market_title: str
    side: str  # UP/DOWN or YES/NO
    qty: float
    entry_price: float
    entry_time: datetime
    gabagool_price: float  # What gabagool got
    our_latency_ms: int  # How late we were
    venue: str  # POLYMARKET or KALSHI
    status: str = "open"  # open, closed, settled
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    pnl: Optional[float] = None
    settlement_outcome: Optional[str] = None


@dataclass 
class VirtualWallet:
    """Virtual wallet for simulation."""
    venue: str
    initial_balance: float = 200.0
    balance: float = 200.0
    positions: Dict[str, Position] = field(default_factory=dict)
    closed_trades: List[Position] = field(default_factory=list)
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    
    @property
    def total_pnl(self) -> float:
        return sum(t.pnl or 0 for t in self.closed_trades)
    
    @property
    def win_rate(self) -> float:
        total = self.wins + self.losses
        return self.wins / total if total > 0 else 0
    
    @property
    def open_exposure(self) -> float:
        return sum(p.qty * p.entry_price for p in self.positions.values())


# ============================================================================
# GABAGOOL SHADOW COPIER
# ============================================================================

class GabagoolShadowCopier:
    """
    Real-time shadow copy of gabagool's trades.
    
    Simulates on both Polymarket (exact) and Kalshi (with latency/slippage).
    """
    
    GABAGOOL_WALLET = "0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d"
    DATA_API = "https://data-api.polymarket.com"
    GAMMA_API = "https://gamma-api.polymarket.com"
    
    def __init__(self, starting_balance: float = 200.0):
        # Virtual wallets
        self.poly_wallet = VirtualWallet(venue="POLYMARKET", initial_balance=starting_balance, balance=starting_balance)
        self.kalshi_wallet = VirtualWallet(venue="KALSHI", initial_balance=starting_balance, balance=starting_balance)
        
        # Price feed for settlement
        self.btc_feed: Optional[LiveBTCFeed] = None
        
        # Track seen trades
        self.seen_trade_ids: Set[str] = set()
        self.last_poll_time = 0
        
        # Market tracking
        self.market_start_prices: Dict[str, float] = {}  # market_id -> start BTC price
        self.market_end_times: Dict[str, datetime] = {}  # market_id -> settlement time
        
        # Session
        self.session: Optional[aiohttp.ClientSession] = None
        self.running = False
        
        # Data persistence
        self.data_dir = Path("data/gabagool_shadow")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Scaling - PROPORTIONAL COPY (100% trade capture)
        # Gabagool avg ~$7/trade, we do ~$4/trade (56% scale)
        self.gabagool_portfolio_estimate = 356  # His peak deployment
        self.our_scale = starting_balance / self.gabagool_portfolio_estimate
        self.min_trade_size = 8.0  # ~$4 per trade at avg price
        self.max_trade_size = 8.0  # Fixed for consistency
        self.max_open_positions = 100  # Effectively unlimited - capture ALL trades
        
        # Latency simulation for Kalshi
        self.kalshi_latency_ms = 2000  # 2 second delay
        self.kalshi_slippage_bps = 50  # 0.5% slippage
        
        # Load previous state
        self._load_state()
    
    def _load_state(self):
        """Load previous state from disk, including open positions."""
        # Load seen trade IDs from state file
        state_file = self.data_dir / "state.json"
        if state_file.exists():
            try:
                with open(state_file) as f:
                    state = json.load(f)
                    self.seen_trade_ids = set(state.get("seen_trade_ids", []))
            except Exception as e:
                print(f"⚠️ Could not load state: {e}")
        
        # Load positions and calculate balances from trades.jsonl (source of truth)
        trades_file = self.data_dir / "trades.jsonl"
        if trades_file.exists():
            try:
                poly_open = []
                poly_settled = []
                kalshi_open = []
                kalshi_settled = []
                
                with open(trades_file) as f:
                    for line in f:
                        if not line.strip():
                            continue
                        t = json.loads(line)
                        venue = t.get('venue', '')
                        status = t.get('status', '')
                        
                        if venue == 'POLYMARKET':
                            if status == 'open':
                                poly_open.append(t)
                            elif status in ('settled', 'closed'):
                                poly_settled.append(t)
                        elif venue == 'KALSHI':
                            if status == 'open':
                                kalshi_open.append(t)
                            elif status in ('settled', 'closed'):
                                kalshi_settled.append(t)
                
                # Calculate balances
                poly_deployed = sum(t.get('qty', 0) * t.get('entry_price', 0) for t in poly_open)
                poly_pnl = sum(t.get('pnl', 0) or 0 for t in poly_settled)
                self.poly_wallet.balance = 200 - poly_deployed + poly_pnl
                self.poly_wallet.wins = len([t for t in poly_settled if (t.get('pnl') or 0) > 0])
                self.poly_wallet.losses = len([t for t in poly_settled if (t.get('pnl') or 0) <= 0])
                
                kalshi_deployed = sum(t.get('qty', 0) * t.get('entry_price', 0) for t in kalshi_open)
                kalshi_pnl = sum(t.get('pnl', 0) or 0 for t in kalshi_settled)
                self.kalshi_wallet.balance = 200 - kalshi_deployed + kalshi_pnl
                self.kalshi_wallet.wins = len([t for t in kalshi_settled if (t.get('pnl') or 0) > 0])
                self.kalshi_wallet.losses = len([t for t in kalshi_settled if (t.get('pnl') or 0) <= 0])
                
                # Load open positions into memory
                for t in poly_open:
                    pos = Position(
                        market_id=t.get('market_id', ''),
                        market_title=t.get('market_title', ''),
                        side=t.get('side', ''),
                        qty=t.get('qty', 0),
                        entry_price=t.get('entry_price', 0),
                        entry_time=datetime.fromisoformat(t.get('entry_time', datetime.now().isoformat())),
                        gabagool_price=t.get('gabagool_price', 0),
                        our_latency_ms=t.get('our_latency_ms', 0),
                        venue='POLYMARKET',
                        status='open'
                    )
                    key = f"{pos.market_id}_{pos.side}"
                    self.poly_wallet.positions[key] = pos
                
                for t in kalshi_open:
                    pos = Position(
                        market_id=t.get('market_id', ''),
                        market_title=t.get('market_title', ''),
                        side=t.get('side', ''),
                        qty=t.get('qty', 0),
                        entry_price=t.get('entry_price', 0),
                        entry_time=datetime.fromisoformat(t.get('entry_time', datetime.now().isoformat())),
                        gabagool_price=t.get('gabagool_price', 0),
                        our_latency_ms=t.get('our_latency_ms', 0),
                        venue='KALSHI',
                        status='open'
                    )
                    key = f"{pos.market_id}_{pos.side}"
                    self.kalshi_wallet.positions[key] = pos
                
                print(f"📂 Loaded: POLY=${self.poly_wallet.balance:.2f} ({len(poly_open)} open), KALSHI=${self.kalshi_wallet.balance:.2f} ({len(kalshi_open)} open)")
                print(f"   Settled: {len(poly_settled) + len(kalshi_settled)} trades, P&L: ${poly_pnl + kalshi_pnl:+.2f}")
                
            except Exception as e:
                print(f"⚠️ Could not load trades: {e}")
                import traceback
                traceback.print_exc()
    
    def _save_state(self):
        """Save current state to disk."""
        state = {
            "seen_trade_ids": list(self.seen_trade_ids)[-1000:],  # Keep last 1000
            "poly_balance": self.poly_wallet.balance,
            "kalshi_balance": self.kalshi_wallet.balance,
            "poly_wins": self.poly_wallet.wins,
            "poly_losses": self.poly_wallet.losses,
            "kalshi_wins": self.kalshi_wallet.wins,
            "kalshi_losses": self.kalshi_wallet.losses,
            "last_updated": datetime.now().isoformat()
        }
        with open(self.data_dir / "state.json", "w") as f:
            json.dump(state, f, indent=2)
    
    def _log_trade(self, position: Position):
        """Log trade to JSONL file."""
        with open(self.data_dir / "trades.jsonl", "a") as f:
            data = asdict(position)
            data["entry_time"] = position.entry_time.isoformat()
            if position.exit_time:
                data["exit_time"] = position.exit_time.isoformat()
            f.write(json.dumps(data) + "\n")
    
    def _update_trade_in_file(self, market_id: str, side: str, venue: str, updates: dict):
        """Update a trade's status in the JSONL file."""
        trades_file = self.data_dir / "trades.jsonl"
        if not trades_file.exists():
            return
        
        # Read all trades
        all_trades = []
        with open(trades_file) as f:
            for line in f:
                if line.strip():
                    all_trades.append(json.loads(line))
        
        # Find and update the matching open trade
        updated = False
        for t in all_trades:
            if (t.get('market_id') == market_id and 
                t.get('side') == side and 
                t.get('venue') == venue and 
                t.get('status') == 'open'):
                t.update(updates)
                updated = True
                break  # Only update one
        
        if updated:
            # Write back
            with open(trades_file, 'w') as f:
                for t in all_trades:
                    f.write(json.dumps(t) + "\n")
    
    async def start(self):
        """Start the shadow copier."""
        print("=" * 70)
        print("  🎯 GABAGOOL SHADOW COPY - DUAL SIMULATION")
        print("=" * 70)
        print(f"  Tracking: @gabagool22 ({self.GABAGOOL_WALLET[:10]}...)")
        print(f"  Starting Balance: ${self.poly_wallet.initial_balance:.2f} per venue")
        print()
        print("  Simulating on:")
        print("    📊 POLYMARKET - Exact copy (baseline)")
        print(f"    📈 KALSHI - With {self.kalshi_latency_ms}ms latency + {self.kalshi_slippage_bps}bps slippage")
        print()
        print("  Results update every 15 minutes as markets settle.")
        print("  Press Ctrl+C to stop.")
        print("=" * 70)
        print()
        
        # Initialize
        self.session = aiohttp.ClientSession()
        self.btc_feed = LiveBTCFeed(buffer_size=120)
        await self.btc_feed.start()
        
        self.running = True
        
        # Start background tasks
        poll_task = asyncio.create_task(self._poll_loop())
        settle_task = asyncio.create_task(self._settlement_loop())
        status_task = asyncio.create_task(self._status_loop())
        
        try:
            await asyncio.gather(poll_task, settle_task, status_task)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()
    
    async def stop(self):
        """Stop the shadow copier."""
        self.running = False
        self._save_state()
        
        if self.btc_feed:
            await self.btc_feed.stop()
        if self.session:
            await self.session.close()
        
        print("\n")
        self._print_final_summary()
    
    async def _poll_loop(self):
        """Poll for new gabagool trades every 500ms for lower latency."""
        while self.running:
            try:
                await self._poll_gabagool()
            except Exception as e:
                print(f"⚠️ Poll error: {e}")
            
            await asyncio.sleep(0.5)  # 500ms = 2 req/sec for faster detection
    
    async def _settlement_loop(self):
        """Check for market settlements every 30 seconds."""
        while self.running:
            try:
                await self._check_settlements()
            except Exception as e:
                print(f"⚠️ Settlement error: {e}")
            
            await asyncio.sleep(30)
    
    async def _status_loop(self):
        """Print status every 60 seconds."""
        while self.running:
            await asyncio.sleep(60)
            self._print_status()
    
    async def _poll_gabagool(self):
        """Poll gabagool's activity using multiple endpoints."""
        # Try data-api endpoint first with "maker" param (faster response)
        url = f"{self.DATA_API}/trades"
        params = {
            "maker": self.GABAGOOL_WALLET,  # "maker" returns fresher data
            "limit": 20
        }
        
        try:
            async with self.session.get(url, params=params, timeout=3) as resp:  # Faster timeout
                if resp.status == 200:
                    data = await resp.json()
                    trades = data if isinstance(data, list) else data.get("trades", [])
                    for trade in trades:
                        await self._process_activity(trade)
                    return
        except Exception as e:
            pass  # Try fallback
        
        # Fallback to gamma-api
        url = f"{self.GAMMA_API}/users/{self.GABAGOOL_WALLET}/activity"
        try:
            async with self.session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    activities = data if isinstance(data, list) else data.get("activities", [])
                    for activity in activities:
                        await self._process_activity(activity)
        except Exception as e:
            if "404" not in str(e) and "timeout" not in str(e).lower():
                print(f"⚠️ API error: {e}")
    
    async def _process_activity(self, activity: Dict):
        """Process a gabagool activity."""
        # Generate unique ID using timestamp + market + side
        ts = activity.get("timestamp", 0)
        market_id = activity.get("conditionId", activity.get("marketId", ""))
        side_raw = activity.get("side", activity.get("type", "")).upper()
        outcome_raw = activity.get("outcome", "")
        
        trade_id = f"{ts}_{market_id}_{side_raw}_{outcome_raw}"
        
        if trade_id in self.seen_trade_ids:
            return
        
        self.seen_trade_ids.add(trade_id)
        
        # Parse action type - data-api uses "side" field (BUY/SELL)
        action_type = side_raw
        if action_type not in ("BUY", "SELL"):
            action_type = activity.get("type", "").upper()
            if action_type not in ("BUY", "SELL", "TRADE"):
                return
        
        # Get market info
        market_title = activity.get("title", activity.get("question", "Unknown"))
        
        # Track ALL crypto up/down markets (BTC, ETH, etc)
        title_lower = market_title.lower()
        is_crypto_market = any(x in title_lower for x in ["bitcoin", "btc", "ethereum", "eth", "up or down", "up/down"])
        
        if not is_crypto_market:
            # Still process non-crypto if gabagool trades it, just note it
            pass
        
        # Parse outcome (UP/DOWN or YES/NO)
        outcome = outcome_raw.upper()
        if outcome in ("UP", "YES", "LONG"):
            side = "UP"
        elif outcome in ("DOWN", "NO", "SHORT"):
            side = "DOWN"
        else:
            # Try to infer from title
            if "up" in title_lower:
                side = "UP"
            elif "down" in title_lower:
                side = "DOWN"
            else:
                side = outcome if outcome else "UNKNOWN"
        
        gabagool_price = float(activity.get("price", 0))
        gabagool_qty = float(activity.get("size", activity.get("shares", 0)))
        
        if gabagool_qty <= 0 or gabagool_price <= 0:
            return
        
        # Calculate our size
        our_size = gabagool_qty * self.our_scale
        our_size = max(self.min_trade_size, min(self.max_trade_size, our_size))
        
        # Get current BTC price for reference
        current_btc = self.btc_feed.get_current_price() if self.btc_feed else 0
        
        # Parse timestamp (data-api returns seconds, not milliseconds)
        ts = activity.get("timestamp", 0)
        if isinstance(ts, str):
            try:
                trade_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except:
                trade_time = datetime.now()
        elif isinstance(ts, (int, float)):
            # Handle both seconds and milliseconds
            if ts > 1e12:
                trade_time = datetime.fromtimestamp(ts / 1000)
            else:
                trade_time = datetime.fromtimestamp(ts)
        else:
            trade_time = datetime.now()
        
        # Calculate latency (how late we are)
        latency_ms = int((datetime.now() - trade_time).total_seconds() * 1000)
        latency_ms = max(latency_ms, self.kalshi_latency_ms)
        
        now = datetime.now()
        
        # ============================================
        # POLYMARKET SIMULATION (Exact Copy)
        # ============================================
        if action_type in ("BUY", "TRADE"):
            # Open position at gabagool's exact price
            poly_entry_price = gabagool_price
            poly_cost = our_size * poly_entry_price
            
            # Check balance AND position limit
            can_open = (
                poly_cost <= self.poly_wallet.balance and
                len(self.poly_wallet.positions) < self.max_open_positions
            )
            
            if can_open:
                position = Position(
                    market_id=market_id,
                    market_title=market_title,
                    side=side,
                    qty=our_size,
                    entry_price=poly_entry_price,
                    entry_time=now,
                    gabagool_price=gabagool_price,
                    our_latency_ms=0,  # Perfect copy
                    venue="POLYMARKET"
                )
                
                self.poly_wallet.positions[f"{market_id}_{side}"] = position
                self.poly_wallet.balance -= poly_cost
                self.poly_wallet.total_trades += 1
                
                # Store market start price for settlement
                if market_id not in self.market_start_prices:
                    self.market_start_prices[market_id] = current_btc
                
                # Estimate settlement time (15 min from now or from market title)
                self.market_end_times[market_id] = now + timedelta(minutes=15)
                
                self._log_trade(position)
            else:
                if poly_cost > self.poly_wallet.balance:
                    print(f"   ⏸️ POLY: Skipped (need ${poly_cost:.2f}, have ${self.poly_wallet.balance:.2f})")
                else:
                    print(f"   ⏸️ POLY: Skipped (max {self.max_open_positions} positions)")
        
        elif action_type == "SELL":
            # Close position - try exact match first, then any match on market
            key = f"{market_id}_{side}"
            
            # Find matching position
            matched_key = None
            if key in self.poly_wallet.positions:
                matched_key = key
            else:
                # Try finding any position on this market
                for k in self.poly_wallet.positions:
                    if k.startswith(market_id):
                        matched_key = k
                        break
            
            if matched_key:
                pos = self.poly_wallet.positions[matched_key]
                pos.exit_price = gabagool_price
                pos.exit_time = now
                pos.status = "closed"
                
                # Calculate P&L: sold price - bought price
                pos.pnl = pos.qty * (pos.exit_price - pos.entry_price)
                
                self.poly_wallet.balance += pos.qty * pos.exit_price
                
                if pos.pnl > 0:
                    self.poly_wallet.wins += 1
                else:
                    self.poly_wallet.losses += 1
                
                self.poly_wallet.closed_trades.append(pos)
                del self.poly_wallet.positions[matched_key]
                
                self._log_trade(pos)
                
                print(f"   📤 POLY closed: {pos.side} @ {pos.entry_price:.3f} → {pos.exit_price:.3f} = ${pos.pnl:+.2f}")
            else:
                print(f"   ⚠️ POLY: No position found to close for {market_id[:20]}...")
        
        # ============================================
        # KALSHI SIMULATION (With Latency + Slippage)
        # ============================================
        if action_type in ("BUY", "TRADE"):
            # Apply slippage - we get worse price due to latency
            slippage = self.kalshi_slippage_bps / 10000
            kalshi_entry_price = gabagool_price * (1 + slippage)  # Pay more
            kalshi_entry_price = min(0.95, kalshi_entry_price)  # Cap at 95 cents
            
            kalshi_cost = our_size * kalshi_entry_price
            
            # Check balance AND position limit
            can_open = (
                kalshi_cost <= self.kalshi_wallet.balance and
                len(self.kalshi_wallet.positions) < self.max_open_positions
            )
            
            if can_open:
                position = Position(
                    market_id=market_id,
                    market_title=market_title,
                    side=side,
                    qty=our_size,
                    entry_price=kalshi_entry_price,
                    entry_time=now,
                    gabagool_price=gabagool_price,
                    our_latency_ms=latency_ms,
                    venue="KALSHI"
                )
                
                self.kalshi_wallet.positions[f"{market_id}_{side}"] = position
                self.kalshi_wallet.balance -= kalshi_cost
                self.kalshi_wallet.total_trades += 1
                
                self._log_trade(position)
        
        elif action_type == "SELL":
            key = f"{market_id}_{side}"
            
            # Find matching position
            matched_key = None
            if key in self.kalshi_wallet.positions:
                matched_key = key
            else:
                # Try finding any position on this market
                for k in self.kalshi_wallet.positions:
                    if k.startswith(market_id):
                        matched_key = k
                        break
            
            if matched_key:
                pos = self.kalshi_wallet.positions[matched_key]
                
                # Apply negative slippage on exit (we get worse price)
                slippage = self.kalshi_slippage_bps / 10000
                pos.exit_price = gabagool_price * (1 - slippage)  # Receive less
                pos.exit_time = now
                pos.status = "closed"
                
                # Calculate P&L: sold price - bought price
                pos.pnl = pos.qty * (pos.exit_price - pos.entry_price)
                
                self.kalshi_wallet.balance += pos.qty * pos.exit_price
                
                if pos.pnl > 0:
                    self.kalshi_wallet.wins += 1
                else:
                    self.kalshi_wallet.losses += 1
                
                self.kalshi_wallet.closed_trades.append(pos)
                del self.kalshi_wallet.positions[matched_key]
                
                self._log_trade(pos)
                
                print(f"   📤 KALSHI closed: {pos.side} @ {pos.entry_price:.3f} → {pos.exit_price:.3f} = ${pos.pnl:+.2f}")
            else:
                print(f"   ⚠️ KALSHI: No position found to close for {market_id[:20]}...")
        
        # Print trade notification
        action_emoji = "🟢" if action_type in ("BUY", "TRADE") else "🔴"
        print(f"\n{action_emoji} GABAGOOL {action_type}: {side} on {market_title[:40]}...")
        print(f"   Gabagool: {gabagool_qty:.1f} @ ${gabagool_price:.3f}")
        print(f"   Our copy: {our_size:.1f} shares | Latency: {latency_ms}ms")
        print(f"   BTC: ${current_btc:,.2f}")
        
        self._save_state()
    
    def _parse_end_time_et(self, title: str):
        """Parse end time from market title (returns hour, minute in ET)."""
        import re
        
        # Try full range format first: "9:45PM-10:00PM"
        match = re.search(r'(\d{1,2}):?(\d{2})?(PM|AM)-(\d{1,2}):?(\d{2})?(PM|AM)', title)
        if match:
            end_h = int(match.group(4))
            end_m = int(match.group(5) or 0)
            ampm = match.group(6)
            if ampm == "PM" and end_h != 12:
                end_h += 12
            elif ampm == "AM" and end_h == 12:
                end_h = 0
            return (end_h, end_m)
        
        # Try single time format: "10PM ET" - assume 15 min duration
        match = re.search(r'(\d{1,2})(PM|AM)\s+ET', title)
        if match:
            h = int(match.group(1))
            ampm = match.group(2)
            if ampm == "PM" and h != 12:
                h += 12
            elif ampm == "AM" and h == 12:
                h = 0
            # Add 15 minutes for end time
            end_m = 15
            end_h = h
            if end_m >= 60:
                end_m -= 60
                end_h += 1
            return (end_h, end_m)
        
        return None
    
    async def _check_settlements(self):
        """Check for market settlements based on BTC price and ET time."""
        import pytz
        et = pytz.timezone('America/New_York')
        now_et = datetime.now(et)
        current_h = now_et.hour
        current_m = now_et.minute
        
        current_btc = self.btc_feed.get_current_price() if self.btc_feed else 0
        
        if not current_btc:
            return
        
        # Check each wallet's positions
        for wallet in [self.poly_wallet, self.kalshi_wallet]:
            positions_to_settle = []
            
            for key, pos in list(wallet.positions.items()):
                # Parse end time from market title
                end_time = self._parse_end_time_et(pos.market_title)
                
                if end_time:
                    end_h, end_m = end_time
                    # Check if market has expired in ET
                    if current_h > end_h or (current_h == end_h and current_m >= end_m):
                        positions_to_settle.append((key, pos))
            
            for key, pos in positions_to_settle:
                # Get start price
                start_price = self.market_start_prices.get(pos.market_id, current_btc)
                
                # Determine outcome based on BTC direction
                if current_btc > start_price:
                    outcome = "UP"
                else:
                    outcome = "DOWN"
                
                pos.settlement_outcome = outcome
                pos.status = "settled"
                
                # Calculate payout
                if pos.side == outcome:
                    # Win - get $1 per share
                    payout = pos.qty * 1.0
                    pos.pnl = payout - (pos.qty * pos.entry_price)
                    wallet.wins += 1
                else:
                    # Lose - get $0
                    payout = 0
                    pos.pnl = -(pos.qty * pos.entry_price)
                    wallet.losses += 1
                
                wallet.balance += payout
                wallet.closed_trades.append(pos)
                del wallet.positions[key]
                
                # Update trade in file (don't append, update existing)
                self._update_trade_in_file(
                    pos.market_id, 
                    pos.side, 
                    wallet.venue,
                    {
                        'status': 'settled',
                        'settlement_outcome': outcome,
                        'pnl': pos.pnl
                    }
                )
                
                # Print settlement
                emoji = "✅" if pos.pnl > 0 else "❌"
                print(f"\n{emoji} SETTLED [{wallet.venue}]: {pos.market_title[:30]}...")
                print(f"   Our bet: {pos.side} @ {pos.entry_price:.3f}")
                print(f"   Outcome: {outcome} | P&L: ${pos.pnl:+.2f}")
        
        self._save_state()
    
    def _print_status(self):
        """Print current status."""
        now = datetime.now().strftime("%H:%M:%S")
        btc = self.btc_feed.get_current_price() if self.btc_feed else 0
        
        print(f"\n{'─' * 70}")
        print(f"📊 STATUS @ {now} | BTC: ${btc:,.2f}")
        print(f"{'─' * 70}")
        
        for name, wallet in [("POLYMARKET", self.poly_wallet), ("KALSHI", self.kalshi_wallet)]:
            open_pos = len(wallet.positions)
            total_pnl = wallet.total_pnl
            pnl_color = "+" if total_pnl >= 0 else ""
            
            print(f"  {name:12} | Balance: ${wallet.balance:>7.2f} | "
                  f"P&L: ${pnl_color}{total_pnl:>6.2f} | "
                  f"Open: {open_pos} | W/L: {wallet.wins}/{wallet.losses}")
        
        print(f"{'─' * 70}")
    
    def _print_final_summary(self):
        """Print final summary."""
        print("=" * 70)
        print("  📈 FINAL SUMMARY")
        print("=" * 70)
        
        for name, wallet in [("POLYMARKET", self.poly_wallet), ("KALSHI", self.kalshi_wallet)]:
            print(f"\n  {name}:")
            print(f"    Starting:   ${wallet.initial_balance:.2f}")
            print(f"    Final:      ${wallet.balance:.2f}")
            print(f"    P&L:        ${wallet.total_pnl:+.2f}")
            print(f"    Return:     {((wallet.balance / wallet.initial_balance) - 1) * 100:+.1f}%")
            print(f"    Trades:     {wallet.total_trades}")
            print(f"    Win Rate:   {wallet.win_rate:.1%}")
        
        print("\n" + "=" * 70)
        print("  Data saved to: data/gabagool_shadow/")
        print("=" * 70)


# ============================================================================
# MAIN
# ============================================================================

async def main():
    copier = GabagoolShadowCopier(starting_balance=200.0)
    
    # Handle shutdown
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(copier.stop()))
    
    await copier.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nShutdown requested...")

