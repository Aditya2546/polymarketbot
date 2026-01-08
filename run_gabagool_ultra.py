#!/usr/bin/env python3
"""
🏎️ ULTRA-FAST GABAGOOL COPY TRADER v3
Maximum speed implementation - targets <3 second latency

OPTIMIZATIONS:
1. uvloop - 2-4x faster event loop
2. orjson - 10x faster JSON parsing
3. Multi-provider WebSocket (5 simultaneous connections)
4. Direct blockchain log decoding (skip API when possible)
5. Pre-calculated position sizes
6. Fire-and-forget execution
7. Connection pooling with keep-alive
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Set, List
from dataclasses import dataclass, field
import time
import hashlib
import signal

# Speed optimizations
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    UVLOOP = True
except ImportError:
    UVLOOP = False

try:
    import orjson
    def json_loads(s): return orjson.loads(s)
    def json_dumps(o): return orjson.dumps(o).decode()
    ORJSON = True
except ImportError:
    import json
    def json_loads(s): return json.loads(s)
    def json_dumps(o): return json.dumps(o)
    ORJSON = False

import aiohttp

try:
    import websockets
    WEBSOCKETS = True
except ImportError:
    WEBSOCKETS = False

sys.path.insert(0, str(Path(__file__).parent))

# =============================================================================
# CONFIGURATION
# =============================================================================

GABAGOOL = "0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d"
GABAGOOL_HEX = GABAGOOL[2:].lower()  # Pre-stripped for fast comparison

# Polymarket CTF Exchange
CTF_EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"

# Multiple FREE WebSocket endpoints for redundancy
WS_ENDPOINTS = [
    "wss://polygon-bor-rpc.publicnode.com",
    "wss://polygon.drpc.org", 
    "wss://polygon-mainnet.public.blastapi.io",
]

# Trading config
STARTING_BALANCE = 200.0
POSITION_SIZES = [5.0, 4.0, 3.0, 2.5, 2.0, 1.5, 1.0]  # Pre-calculated tiers
MAX_POSITIONS = 100

# =============================================================================
# DATA STRUCTURES (minimal for speed)
# =============================================================================

@dataclass
class Position:
    market_id: str
    title: str
    side: str
    qty: float
    price: float
    entry_time: float  # Unix timestamp (faster than datetime)
    venue: str
    slug: str = ""
    outcome: str = ""
    pnl: float = 0.0

@dataclass 
class Wallet:
    venue: str
    balance: float = 200.0
    positions: Dict[str, Position] = field(default_factory=dict)
    wins: int = 0
    losses: int = 0

# =============================================================================
# ULTRA-FAST COPY TRADER
# =============================================================================

class UltraFastTrader:
    __slots__ = ['running', 'session', 'poly', 'kalshi', 'seen', 'stats', 
                 'data_dir', 'last_api_trades', 'position_tier']
    
    def __init__(self):
        self.running = False
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Wallets
        self.poly = Wallet("POLY", STARTING_BALANCE)
        self.kalshi = Wallet("KALSHI", STARTING_BALANCE)
        
        # Fast dedup using set (O(1) lookup)
        self.seen: Set[str] = set()
        
        # Stats
        self.stats = {'detected': 0, 'copied': 0, 'latencies': []}
        
        # Pre-calculate position tier based on open positions
        self.position_tier = 0
        
        # Data
        self.data_dir = Path("data/gabagool_ultra")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Cache last API response for dedup
        self.last_api_trades: Set[str] = set()
        
        self._load_state()
        
    def _load_state(self):
        state_file = self.data_dir / "state.json"
        if state_file.exists():
            try:
                with open(state_file, 'rb') as f:
                    state = json_loads(f.read())
                self.poly.balance = state.get('poly_balance', STARTING_BALANCE)
                self.kalshi.balance = state.get('kalshi_balance', STARTING_BALANCE)
                self.poly.wins = state.get('poly_wins', 0)
                self.poly.losses = state.get('poly_losses', 0)
                self.kalshi.wins = state.get('kalshi_wins', 0)
                self.kalshi.losses = state.get('kalshi_losses', 0)
                self.seen = set(state.get('seen', [])[-2000:])
            except:
                pass
                
    def _save_state(self):
        state = {
            'poly_balance': self.poly.balance,
            'kalshi_balance': self.kalshi.balance,
            'poly_wins': self.poly.wins,
            'poly_losses': self.poly.losses,
            'kalshi_wins': self.kalshi.wins,
            'kalshi_losses': self.kalshi.losses,
            'seen': list(self.seen)[-2000:],
            'ts': time.time()
        }
        with open(self.data_dir / "state.json", 'wb') as f:
            f.write(orjson.dumps(state) if ORJSON else json_dumps(state).encode())
            
    async def start(self):
        print("="*70)
        print("🏎️  ULTRA-FAST GABAGOOL COPY TRADER v3")
        print("="*70)
        print(f"   uvloop: {'✅' if UVLOOP else '❌'} | orjson: {'✅' if ORJSON else '❌'}")
        print(f"   WebSocket providers: {len(WS_ENDPOINTS)}")
        print(f"   Balance: ${self.poly.balance:.2f} POLY / ${self.kalshi.balance:.2f} KALSHI")
        print("="*70 + "\n")
        
        self.running = True
        
        # Optimized connection pooling
        connector = aiohttp.TCPConnector(
            limit=50,
            ttl_dns_cache=300,
            keepalive_timeout=60,
            enable_cleanup_closed=True
        )
        timeout = aiohttp.ClientTimeout(total=3, connect=1)
        self.session = aiohttp.ClientSession(connector=connector, timeout=timeout)
        
        # Build tasks
        tasks = [
            self._api_poller(),       # Fast API backup
            self._settlement_loop(),
            self._status_loop()
        ]
        
        # Add WebSocket monitors (one per provider)
        if WEBSOCKETS:
            for i, endpoint in enumerate(WS_ENDPOINTS[:3]):  # Top 3 providers
                tasks.append(self._ws_monitor(endpoint, i))
        
        try:
            await asyncio.gather(*tasks)
        finally:
            await self.stop()
            
    async def stop(self):
        self.running = False
        self._save_state()
        if self.session:
            await self.session.close()
        print("\n👋 Stopped")

    # =========================================================================
    # WEBSOCKET MONITORS (Multiple simultaneous connections)
    # =========================================================================
    
    async def _ws_monitor(self, endpoint: str, idx: int):
        """Monitor single WebSocket endpoint"""
        provider = endpoint.split('/')[2].split('.')[0]
        
        while self.running:
            try:
                async with websockets.connect(
                    endpoint,
                    ping_interval=20,
                    ping_timeout=30,
                    close_timeout=5
                ) as ws:
                    # Subscribe to CTF Exchange logs
                    sub = {
                        "jsonrpc": "2.0",
                        "method": "eth_subscribe", 
                        "params": ["logs", {"address": CTF_EXCHANGE}],
                        "id": idx
                    }
                    await ws.send(json_dumps(sub))
                    
                    resp = await asyncio.wait_for(ws.recv(), timeout=5)
                    result = json_loads(resp)
                    
                    if 'result' not in result:
                        await asyncio.sleep(5)
                        continue
                        
                    print(f"⚡ WS[{idx}] {provider} connected")
                    
                    # Fast event loop
                    while self.running:
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=0.5)
                            data = json_loads(msg)
                            
                            if 'params' in data:
                                log = data['params'].get('result', {})
                                # Fire and forget - don't await
                                asyncio.create_task(self._process_log(log))
                                
                        except asyncio.TimeoutError:
                            pass
                            
            except Exception as e:
                if "1006" not in str(e):
                    print(f"⚠️ WS[{idx}] error: {str(e)[:50]}")
                await asyncio.sleep(3)

    async def _process_log(self, log: dict):
        """Process blockchain log - check if gabagool involved"""
        tx_hash = log.get('transactionHash', '')
        if not tx_hash or tx_hash in self.seen:
            return
            
        # Fast check if gabagool is in the log
        topics = log.get('topics', [])
        data = log.get('data', '')
        
        # Check all topics and data for gabagool's address
        found = False
        for topic in topics:
            if GABAGOOL_HEX in topic.lower():
                found = True
                break
        if not found and GABAGOOL_HEX in data.lower():
            found = True
            
        if not found:
            return
            
        self.seen.add(tx_hash)
        detection_time = time.time()
        
        print(f"\n⚡ BLOCKCHAIN: {tx_hash[:30]}...")
        
        # Immediately fetch from API (don't wait)
        asyncio.create_task(self._fast_fetch(tx_hash, detection_time))

    async def _fast_fetch(self, tx_hash: str, detection_time: float):
        """Fetch trade details from API as fast as possible"""
        try:
            url = "https://data-api.polymarket.com/trades"
            params = {"maker": GABAGOOL, "limit": 5}
            
            async with self.session.get(url, params=params) as resp:
                if resp.status == 200:
                    trades = await resp.json()
                    now = time.time()
                    
                    for trade in trades:
                        ts = trade.get('timestamp', 0)
                        if ts > 1e12:
                            ts /= 1000
                        
                        # Only process trades from last 60 seconds
                        if now - ts < 60:
                            await self._execute_copy(trade, detection_time)
                            
        except Exception as e:
            pass  # Silent fail, API backup will catch it

    # =========================================================================
    # API POLLER (Backup)
    # =========================================================================
    
    async def _api_poller(self):
        """Fast API polling as backup"""
        print("📡 API poller started")
        
        while self.running:
            try:
                url = "https://data-api.polymarket.com/trades"
                params = {"maker": GABAGOOL, "limit": 10}
                
                async with self.session.get(url, params=params) as resp:
                    if resp.status == 200:
                        trades = await resp.json()
                        now = time.time()
                        
                        for trade in trades:
                            ts = trade.get('timestamp', 0)
                            if ts > 1e12:
                                ts /= 1000
                                
                            # Only process trades from last 30 seconds
                            if now - ts < 30:
                                await self._execute_copy(trade, now)
                                
            except:
                pass
                
            await asyncio.sleep(1.5)  # Poll every 1.5 seconds

    # =========================================================================
    # TRADE EXECUTION (Optimized)
    # =========================================================================
    
    async def _execute_copy(self, trade: dict, detection_time: float):
        """Execute copy trade with REAL current price"""
        
        # Extract fields once
        asset = trade.get('asset', '')
        side = trade.get('side', 'BUY').upper()
        gabagool_price = float(trade.get('price', 0.5))  # What gabagool paid
        size = float(trade.get('size', 0))
        ts = trade.get('timestamp', 0)
        title = trade.get('title', '')
        slug = trade.get('slug', '')
        outcome = trade.get('outcome', '')
        
        # CRITICAL: Get LIVE price (what we'd actually pay)
        live_price = await self._get_live_price(asset, outcome)
        if live_price:
            price = live_price  # Use real current price
            slippage_pct = ((price - gabagool_price) / gabagool_price) * 100 if gabagool_price > 0 else 0
        else:
            price = gabagool_price * 1.02  # Estimate 2% slippage if can't fetch
            slippage_pct = 2.0
        
        # Fast dedup
        trade_id = f"{asset[:16]}{int(ts)}{side}"
        if trade_id in self.seen:
            return
        self.seen.add(trade_id)
        
        # Calculate latency
        if ts > 1e12:
            ts /= 1000
        latency_ms = int((time.time() - ts) * 1000)
        
        self.stats['detected'] += 1
        self.stats['latencies'].append(latency_ms)
        if len(self.stats['latencies']) > 50:
            self.stats['latencies'] = self.stats['latencies'][-50:]
        
        # Log with slippage info
        emoji = '🟢' if side == 'BUY' else '🔴'
        slip_emoji = '📈' if slippage_pct > 1 else '✓'
        print(f"\n{emoji} COPY: {side} @ ${price:.3f} (gaba: ${gabagool_price:.3f}, slip: {slippage_pct:+.1f}% {slip_emoji})")
        print(f"   {title[:50]}... | {latency_ms}ms")
        
        if side == "BUY":
            # Execute both venues in parallel
            await asyncio.gather(
                self._buy_poly(asset, title, price, slug, outcome, latency_ms),
                self._buy_kalshi(asset, title, price, slug, outcome, latency_ms),
                return_exceptions=True
            )
        else:
            await asyncio.gather(
                self._sell_poly(asset, price),
                self._sell_kalshi(asset, price),
                return_exceptions=True
            )
            
        self.stats['copied'] += 1
        
        # Async save (don't block)
        asyncio.create_task(self._async_save())
        
    async def _async_save(self):
        """Non-blocking state save"""
        try:
            self._save_state()
        except:
            pass

    async def _get_live_price(self, asset: str, outcome: str) -> Optional[float]:
        """Fetch LIVE current price from Polymarket orderbook"""
        try:
            # Polymarket CLOB API for live prices
            url = f"https://clob.polymarket.com/book?token_id={asset}"
            async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=1)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    # Get best ask (LOWEST price we can buy at)
                    # Asks are sorted DESCENDING, so we need the LAST one with liquidity
                    asks = data.get('asks', [])
                    if asks:
                        # Find the lowest ask price
                        ask_prices = [float(a.get('price', 999)) for a in asks]
                        best_ask = min(ask_prices)
                        if best_ask < 1.0:
                            return best_ask
                    
                    # Fallback: use last trade price
                    last_price = data.get('last_trade_price')
                    if last_price:
                        return float(last_price)
                    
                    # If no asks, check if there are bids (indicates market price)
                    bids = data.get('bids', [])
                    if bids:
                        # Best bid is highest, it's sorted descending
                        best_bid = float(bids[0].get('price', 0))
                        # Add small spread to estimate ask
                        return best_bid + 0.01
                        
        except:
            pass
        return None

    def _get_size(self, wallet: Wallet, price: float) -> float:
        """Pre-calculated position sizing - O(1)"""
        n_pos = len(wallet.positions)
        tier = min(n_pos // 15, len(POSITION_SIZES) - 1)
        size_usd = POSITION_SIZES[tier]
        
        # Ensure we have enough balance
        if size_usd > wallet.balance * 0.95:
            size_usd = wallet.balance * 0.5
            
        if size_usd < 1.0 or n_pos >= MAX_POSITIONS:
            return 0
            
        return size_usd / max(price, 0.01)

    async def _buy_poly(self, asset: str, title: str, price: float, 
                        slug: str, outcome: str, latency: int):
        """Buy on Polymarket"""
        qty = self._get_size(self.poly, price)
        if qty <= 0:
            return
            
        cost = qty * price
        self.poly.balance -= cost
        
        pos = Position(
            market_id=asset, title=title, side="BUY", qty=qty,
            price=price, entry_time=time.time(), venue="POLY",
            slug=slug, outcome=outcome
        )
        self.poly.positions[f"{asset[:20]}_{outcome}"] = pos
        
        self._log_trade(pos, latency)
        print(f"   ✅ POLY: {qty:.1f} @ ${price:.3f} = ${cost:.2f}")

    async def _buy_kalshi(self, asset: str, title: str, price: float,
                          slug: str, outcome: str, latency: int):
        """Buy on Kalshi (additional slippage for different venue)"""
        kalshi_price = price * 1.003  # 0.3% extra for Kalshi execution
        qty = self._get_size(self.kalshi, kalshi_price)
        if qty <= 0:
            return
            
        cost = qty * kalshi_price
        self.kalshi.balance -= cost
        
        pos = Position(
            market_id=asset, title=title, side="BUY", qty=qty,
            price=kalshi_price, entry_time=time.time(), venue="KALSHI",
            slug=slug, outcome=outcome
        )
        self.kalshi.positions[f"{asset[:20]}_{outcome}"] = pos
        
        self._log_trade(pos, latency + 2000)
        print(f"   ✅ KALSHI: {qty:.1f} @ ${kalshi_price:.3f} = ${cost:.2f}")

    async def _sell_poly(self, asset: str, exit_price: float):
        """Sell on Polymarket"""
        key = None
        for k in self.poly.positions:
            if k.startswith(asset[:20]):
                key = k
                break
                
        if key:
            pos = self.poly.positions[key]
            pos.pnl = pos.qty * (exit_price - pos.price)
            self.poly.balance += pos.qty * exit_price
            
            if pos.pnl > 0:
                self.poly.wins += 1
            else:
                self.poly.losses += 1
                
            del self.poly.positions[key]
            
            emoji = "✅" if pos.pnl > 0 else "❌"
            print(f"   {emoji} POLY CLOSE: ${pos.price:.3f} → ${exit_price:.3f} = ${pos.pnl:+.2f}")

    async def _sell_kalshi(self, asset: str, exit_price: float):
        """Sell on Kalshi"""
        key = None
        for k in self.kalshi.positions:
            if k.startswith(asset[:20]):
                key = k
                break
                
        if key:
            pos = self.kalshi.positions[key]
            kalshi_exit = exit_price * 0.995  # Slippage on exit
            pos.pnl = pos.qty * (kalshi_exit - pos.price)
            self.kalshi.balance += pos.qty * kalshi_exit
            
            if pos.pnl > 0:
                self.kalshi.wins += 1
            else:
                self.kalshi.losses += 1
                
            del self.kalshi.positions[key]
            
            emoji = "✅" if pos.pnl > 0 else "❌"
            print(f"   {emoji} KALSHI CLOSE: ${pos.price:.3f} → ${kalshi_exit:.3f} = ${pos.pnl:+.2f}")

    def _log_trade(self, pos: Position, latency: int):
        """Fast trade logging"""
        data = {
            'market': pos.market_id[:30],
            'title': pos.title[:50],
            'side': pos.side,
            'qty': round(pos.qty, 2),
            'price': round(pos.price, 4),
            'ts': pos.entry_time,
            'venue': pos.venue,
            'slug': pos.slug,
            'outcome': pos.outcome,
            'latency': latency
        }
        try:
            with open(self.data_dir / "trades.jsonl", 'ab') as f:
                f.write(orjson.dumps(data) + b'\n' if ORJSON else (json_dumps(data) + '\n').encode())
        except:
            pass

    # =========================================================================
    # SETTLEMENT
    # =========================================================================
    
    async def _settlement_loop(self):
        """Settle positions using Polymarket outcomes"""
        while self.running:
            try:
                now = time.time()
                
                for wallet in [self.poly, self.kalshi]:
                    for key, pos in list(wallet.positions.items()):
                        age = now - pos.entry_time
                        
                        if age > 900:  # 15 min
                            winner = await self._get_outcome(pos.slug)
                            
                            if winner:
                                won = pos.outcome.lower() == winner.lower() if pos.outcome else False
                                
                                if won:
                                    pos.pnl = pos.qty * (1.0 - pos.price)
                                    wallet.wins += 1
                                    wallet.balance += pos.qty
                                else:
                                    pos.pnl = -pos.qty * pos.price
                                    wallet.losses += 1
                                    
                                del wallet.positions[key]
                                
                                emoji = '✅' if won else '❌'
                                print(f"\n{emoji} SETTLED ({wallet.venue}): {pos.title[:30]}... = ${pos.pnl:+.2f}")
                                
                self._save_state()
                
            except Exception as e:
                pass
                
            await asyncio.sleep(30)

    async def _get_outcome(self, slug: str) -> Optional[str]:
        """Get market outcome from Polymarket"""
        if not slug:
            return None
            
        try:
            url = f"https://gamma-api.polymarket.com/markets?slug={slug}"
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    if isinstance(data, list) and data:
                        market = data[0]
                        
                        if market.get('resolved'):
                            return market.get('resolution')
                            
                        # Check prices
                        outcomes = market.get('outcomes', [])
                        prices = market.get('outcomePrices', [])
                        
                        if isinstance(prices, str):
                            prices = json_loads(prices)
                        if isinstance(outcomes, str):
                            outcomes = json_loads(outcomes)
                            
                        for i, p in enumerate(prices):
                            if float(p) > 0.90:
                                return outcomes[i]
                                
        except:
            pass
        return None

    # =========================================================================
    # STATUS
    # =========================================================================
    
    async def _status_loop(self):
        """Print status"""
        while self.running:
            await asyncio.sleep(60)
            
            avg_lat = sum(self.stats['latencies']) / max(len(self.stats['latencies']), 1)
            
            print("\n" + "─"*60)
            print(f"📊 STATUS @ {datetime.now().strftime('%H:%M:%S')}")
            print(f"   POLY:   ${self.poly.balance:>7.2f} | {len(self.poly.positions)} pos | {self.poly.wins}W/{self.poly.losses}L")
            print(f"   KALSHI: ${self.kalshi.balance:>7.2f} | {len(self.kalshi.positions)} pos | {self.kalshi.wins}W/{self.kalshi.losses}L")
            print(f"   Detected: {self.stats['detected']} | Copied: {self.stats['copied']} | Avg: {avg_lat:.0f}ms")
            print("─"*60)

# =============================================================================
# MAIN
# =============================================================================

async def main():
    trader = UltraFastTrader()
    
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(trader.stop()))
        
    await trader.start()

if __name__ == "__main__":
    print("🏎️  Starting Ultra-Fast Trader...")
    asyncio.run(main())
