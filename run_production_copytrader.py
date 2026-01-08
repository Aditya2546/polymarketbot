#!/usr/bin/env python3
"""
🏛️ PRODUCTION-GRADE GABAGOOL COPY TRADER
Real prices, real costs, real risk management

ALL costs accounted for:
- Real orderbook prices (not gabagool's)
- Trading fees (2% Polymarket, 7% Kalshi profit fee)
- Gas fees (~$0.05 per trade)
- Slippage from latency
- Bid-ask spread
- Market impact
- Partial fills
"""
import asyncio
import aiohttp
import json
import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Set
import time
import hashlib

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
    def json_loads(s): return json.loads(s)
    def json_dumps(o): return json.dumps(o)
    ORJSON = False

try:
    import websockets
    WEBSOCKETS = True
except ImportError:
    WEBSOCKETS = False

sys.path.insert(0, str(Path(__file__).parent))

from src.copytrader.config import CONFIG
from src.copytrader.orderbook import OrderbookFetcher
from src.copytrader.execution import ExecutionEngine
from src.copytrader.risk import RiskManager, Wallet, Position

# WebSocket endpoints
WS_ENDPOINTS = [
    "wss://polygon-bor-rpc.publicnode.com",
    "wss://polygon.drpc.org",
]

CTF_EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
GABAGOOL_HEX = CONFIG.GABAGOOL_ADDRESS[2:].lower()


class ProductionCopyTrader:
    """
    Production-grade copy trading with REAL costs
    """
    
    def __init__(self):
        self.running = False
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Components
        self.orderbook: Optional[OrderbookFetcher] = None
        self.execution: Optional[ExecutionEngine] = None
        self.risk = RiskManager()
        
        # Wallets
        self.poly = Wallet(
            venue="POLYMARKET",
            starting_balance=CONFIG.STARTING_BALANCE,
            balance=CONFIG.STARTING_BALANCE
        )
        self.kalshi = Wallet(
            venue="KALSHI", 
            starting_balance=CONFIG.STARTING_BALANCE,
            balance=CONFIG.STARTING_BALANCE
        )
        
        # Deduplication
        self.seen: Set[str] = set()
        
        # Stats
        self.stats = {
            'detected': 0,
            'executed': 0,
            'skipped_slippage': 0,
            'skipped_liquidity': 0,
            'skipped_risk': 0,
            'failed': 0,
            'latencies': []
        }
        
        # Data directory
        self.data_dir = Path("data/production_copytrader")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self._load_state()
    
    def _load_state(self):
        """Load saved state"""
        state_file = self.data_dir / "state.json"
        if state_file.exists():
            try:
                with open(state_file, 'rb') as f:
                    state = json_loads(f.read())
                
                self.poly.balance = state.get('poly_balance', CONFIG.STARTING_BALANCE)
                self.poly.wins = state.get('poly_wins', 0)
                self.poly.losses = state.get('poly_losses', 0)
                self.poly.total_fees_paid = state.get('poly_fees', 0)
                self.poly.total_slippage_cost = state.get('poly_slippage', 0)
                
                self.kalshi.balance = state.get('kalshi_balance', CONFIG.STARTING_BALANCE)
                self.kalshi.wins = state.get('kalshi_wins', 0)
                self.kalshi.losses = state.get('kalshi_losses', 0)
                self.kalshi.total_fees_paid = state.get('kalshi_fees', 0)
                
                self.seen = set(state.get('seen', [])[-2000:])
                
                # Restore open positions
                for pos_data in state.get('poly_positions', []):
                    pos = Position(**pos_data)
                    key = f"{pos.market_id[:20]}_{pos.outcome}"
                    self.poly.positions[key] = pos
                
                for pos_data in state.get('kalshi_positions', []):
                    pos = Position(**pos_data)
                    key = f"{pos.market_id[:20]}_{pos.outcome}"
                    self.kalshi.positions[key] = pos
                
                print(f"📂 Restored {len(self.poly.positions)} POLY + {len(self.kalshi.positions)} KALSHI positions")
            except Exception as e:
                print(f"⚠️ State load error: {e}")
    
    def _save_state(self):
        """Save state to disk"""
        # Serialize positions
        poly_positions = []
        for key, pos in self.poly.positions.items():
            poly_positions.append({
                'market_id': pos.market_id,
                'title': pos.title,
                'side': pos.side,
                'outcome': pos.outcome,
                'slug': pos.slug,
                'qty': pos.qty,
                'entry_price': pos.entry_price,
                'entry_time': pos.entry_time,
                'fees_paid': pos.fees_paid,
                'slippage_pct': pos.slippage_pct,
                'venue': pos.venue,
                'gabagool_price': pos.gabagool_price,
                'status': pos.status
            })
        
        kalshi_positions = []
        for key, pos in self.kalshi.positions.items():
            kalshi_positions.append({
                'market_id': pos.market_id,
                'title': pos.title,
                'side': pos.side,
                'outcome': pos.outcome,
                'slug': pos.slug,
                'qty': pos.qty,
                'entry_price': pos.entry_price,
                'entry_time': pos.entry_time,
                'fees_paid': pos.fees_paid,
                'slippage_pct': pos.slippage_pct,
                'venue': pos.venue,
                'gabagool_price': pos.gabagool_price,
                'status': pos.status
            })
        
        state = {
            'poly_balance': self.poly.balance,
            'poly_wins': self.poly.wins,
            'poly_losses': self.poly.losses,
            'poly_fees': self.poly.total_fees_paid,
            'poly_slippage': self.poly.total_slippage_cost,
            'poly_positions': poly_positions,
            'kalshi_balance': self.kalshi.balance,
            'kalshi_wins': self.kalshi.wins,
            'kalshi_losses': self.kalshi.losses,
            'kalshi_fees': self.kalshi.total_fees_paid,
            'kalshi_positions': kalshi_positions,
            'seen': list(self.seen)[-2000:],
            'timestamp': time.time()
        }
        with open(self.data_dir / "state.json", 'wb') as f:
            f.write(orjson.dumps(state) if ORJSON else json_dumps(state).encode())
    
    async def start(self):
        """Start the copy trader"""
        print("="*70)
        print("🏛️  PRODUCTION GABAGOOL COPY TRADER")
        print("="*70)
        print(f"   uvloop: {'✅' if UVLOOP else '❌'} | orjson: {'✅' if ORJSON else '❌'}")
        print()
        print("   💰 COST MODEL:")
        print(f"      Polymarket: {CONFIG.poly_fees.TAKER_FEE*100:.0f}% fee + ${CONFIG.poly_fees.GAS_FEE_USD:.2f} gas")
        print(f"      Kalshi: {CONFIG.kalshi_fees.PROFIT_FEE_RATE*100:.0f}% profit fee + {CONFIG.kalshi_fees.EXCHANGE_FEE*100:.0f}% exchange fee")
        print(f"      Max slippage: {CONFIG.risk.MAX_SLIPPAGE_PCT*100:.0f}%")
        print()
        print(f"   📊 RISK LIMITS:")
        print(f"      Max position: ${CONFIG.risk.MAX_POSITION_USD:.0f}")
        print(f"      Max open: {CONFIG.risk.MAX_OPEN_POSITIONS}")
        print(f"      Daily drawdown limit: {CONFIG.risk.MAX_DAILY_DRAWDOWN_PCT*100:.0f}%")
        print()
        print(f"   💵 Balance: ${self.poly.balance:.2f} POLY / ${self.kalshi.balance:.2f} KALSHI")
        print("="*70 + "\n")
        
        self.running = True
        
        # Setup HTTP session
        connector = aiohttp.TCPConnector(limit=50, ttl_dns_cache=300, keepalive_timeout=60)
        timeout = aiohttp.ClientTimeout(total=5, connect=2)
        self.session = aiohttp.ClientSession(connector=connector, timeout=timeout)
        
        # Initialize components
        self.orderbook = OrderbookFetcher(self.session)
        self.execution = ExecutionEngine(self.orderbook)
        
        # Build tasks
        tasks = [
            self._api_poller(),
            self._settlement_loop(),
            self._status_loop()
        ]
        
        if WEBSOCKETS:
            for i, endpoint in enumerate(WS_ENDPOINTS):
                tasks.append(self._ws_monitor(endpoint, i))
        
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()
    
    async def stop(self):
        """Shutdown gracefully"""
        self.running = False
        self._save_state()
        if self.session:
            await self.session.close()
        print("\n👋 Stopped - state saved")
    
    # =========================================================================
    # DETECTION
    # =========================================================================
    
    async def _ws_monitor(self, endpoint: str, idx: int):
        """Monitor blockchain for gabagool trades"""
        provider = endpoint.split('/')[2].split('.')[0]
        
        while self.running:
            try:
                async with websockets.connect(endpoint, ping_interval=20, ping_timeout=30) as ws:
                    sub = {
                        "jsonrpc": "2.0",
                        "method": "eth_subscribe",
                        "params": ["logs", {"address": CTF_EXCHANGE}],
                        "id": idx
                    }
                    await ws.send(json_dumps(sub))
                    
                    resp = await asyncio.wait_for(ws.recv(), timeout=5)
                    if 'result' not in json_loads(resp):
                        await asyncio.sleep(5)
                        continue
                    
                    print(f"⚡ WS[{idx}] {provider} connected")
                    
                    while self.running:
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=0.5)
                            data = json_loads(msg)
                            if 'params' in data:
                                asyncio.create_task(self._process_log(data['params'].get('result', {})))
                        except asyncio.TimeoutError:
                            pass
                            
            except Exception as e:
                if "1006" not in str(e) and "403" not in str(e):
                    print(f"⚠️ WS[{idx}] error: {str(e)[:40]}")
                await asyncio.sleep(3)
    
    async def _process_log(self, log: dict):
        """Process blockchain log"""
        tx_hash = log.get('transactionHash', '')
        if not tx_hash or tx_hash in self.seen:
            return
        
        topics = log.get('topics', [])
        data = log.get('data', '')
        
        found = any(GABAGOOL_HEX in t.lower() for t in topics) or GABAGOOL_HEX in data.lower()
        if not found:
            return
        
        self.seen.add(tx_hash)
        asyncio.create_task(self._fetch_and_execute(tx_hash, time.time()))
    
    async def _api_poller(self):
        """Backup API polling"""
        print("📡 API poller started")
        
        while self.running:
            try:
                url = "https://data-api.polymarket.com/trades"
                params = {"maker": CONFIG.GABAGOOL_ADDRESS, "limit": 10}
                
                async with self.session.get(url, params=params) as resp:
                    if resp.status == 200:
                        trades = await resp.json()
                        now = time.time()
                        
                        for trade in trades:
                            ts = trade.get('timestamp', 0)
                            if ts > 1e12:
                                ts /= 1000
                            if now - ts < 30:
                                await self._execute_trade(trade, now)
            except:
                pass
            
            await asyncio.sleep(1.5)
    
    async def _fetch_and_execute(self, tx_hash: str, detection_time: float):
        """Fetch trade details and execute"""
        try:
            url = "https://data-api.polymarket.com/trades"
            params = {"maker": CONFIG.GABAGOOL_ADDRESS, "limit": 5}
            
            async with self.session.get(url, params=params) as resp:
                if resp.status == 200:
                    trades = await resp.json()
                    now = time.time()
                    
                    for trade in trades:
                        ts = trade.get('timestamp', 0)
                        if ts > 1e12:
                            ts /= 1000
                        if now - ts < 60:
                            await self._execute_trade(trade, detection_time)
        except:
            pass
    
    # =========================================================================
    # EXECUTION
    # =========================================================================
    
    async def _execute_trade(self, trade: dict, detection_time: float):
        """Execute copy trade with REAL costs"""
        
        asset = trade.get('asset', '')
        side = trade.get('side', 'BUY').upper()
        gabagool_price = float(trade.get('price', 0.5))
        gabagool_size = float(trade.get('size', 0))
        ts = trade.get('timestamp', 0)
        title = trade.get('title', '')
        slug = trade.get('slug', '')
        outcome = trade.get('outcome', '')
        
        # Dedup
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
        
        if side == "BUY":
            await self._execute_buy(
                asset, title, slug, outcome,
                gabagool_price, gabagool_size, latency_ms
            )
        else:
            await self._execute_sell(asset, title, latency_ms)
        
        asyncio.create_task(self._async_save())
    
    async def _execute_buy(
        self, asset: str, title: str, slug: str, outcome: str,
        gabagool_price: float, gabagool_size: float, latency_ms: int
    ):
        """Execute BUY with real costs"""
        
        # Calculate position size
        poly_size = self.risk.calculate_position_size(
            self.poly, gabagool_price, gabagool_size, gabagool_price
        )
        kalshi_size = self.risk.calculate_position_size(
            self.kalshi, gabagool_price, gabagool_size, gabagool_price
        )
        
        if poly_size <= 0 and kalshi_size <= 0:
            self.stats['skipped_risk'] += 1
            return
        
        target_usd = poly_size * gabagool_price if poly_size > 0 else kalshi_size * gabagool_price
        
        # Get real orderbook price
        exec_price, fill_rate, liquidity = await self.orderbook.get_execution_price(
            asset, "BUY", target_usd
        )
        
        if exec_price is None:
            exec_price = gabagool_price * 1.02  # Fallback
            liquidity = 100
        
        # Calculate slippage
        slippage_pct = (exec_price - gabagool_price) / gabagool_price if gabagool_price > 0 else 0
        
        # Check if we should skip
        should_skip, skip_reason = self.risk.should_skip_trade(slippage_pct, liquidity, target_usd)
        if should_skip:
            self.stats['skipped_slippage'] += 1
            print(f"\n⏭️ SKIP: {skip_reason}")
            print(f"   {title[:50]}...")
            return
        
        # Log
        emoji = '🟢'
        slip_str = f"{slippage_pct*100:+.1f}%"
        print(f"\n{emoji} COPY BUY:")
        print(f"   Gabagool: ${gabagool_price:.3f} | Market: ${exec_price:.3f} | Slip: {slip_str}")
        print(f"   {title[:50]}... | {latency_ms}ms")
        
        # Execute on both venues
        await asyncio.gather(
            self._buy_polymarket(asset, title, slug, outcome, exec_price, gabagool_price, poly_size, latency_ms, slippage_pct),
            self._buy_kalshi(asset, title, slug, outcome, exec_price, gabagool_price, kalshi_size, latency_ms, slippage_pct),
            return_exceptions=True
        )
        
        self.stats['executed'] += 1
    
    async def _buy_polymarket(
        self, asset: str, title: str, slug: str, outcome: str,
        market_price: float, gabagool_price: float, qty: float,
        latency_ms: int, slippage_pct: float
    ):
        """Execute Polymarket buy with ALL costs"""
        if qty <= 0:
            return
        
        # Execute
        result = await self.execution.execute_polymarket_buy(
            asset, gabagool_price, qty * market_price, latency_ms
        )
        
        if not result.success:
            self.poly.rejected_trades += 1
            self.stats['failed'] += 1
            print(f"   ❌ POLY: {result.reject_reason}")
            return
        
        # Deduct from balance
        self.poly.balance -= result.total_cost
        self.poly.total_fees_paid += result.trading_fee + result.gas_fee
        self.poly.total_slippage_cost += result.slippage_cost
        self.poly.total_trades += 1
        
        # Create position
        pos = Position(
            market_id=asset,
            title=title,
            side="BUY",
            outcome=outcome,
            slug=slug,
            qty=result.executed_qty,
            entry_price=result.executed_price,
            entry_time=time.time(),
            fees_paid=result.trading_fee + result.gas_fee,
            slippage_pct=result.slippage_vs_gabagool_pct,
            venue="POLYMARKET",
            gabagool_price=gabagool_price
        )
        
        self.poly.positions[f"{asset[:20]}_{outcome}"] = pos
        self._log_trade(pos, result, latency_ms)
        
        print(f"   ✅ POLY: {result.executed_qty:.1f} @ ${result.executed_price:.3f}")
        print(f"      Cost: ${result.total_cost:.2f} (fee: ${result.trading_fee:.2f}, gas: ${result.gas_fee:.2f})")
    
    async def _buy_kalshi(
        self, asset: str, title: str, slug: str, outcome: str,
        market_price: float, gabagool_price: float, qty: float,
        latency_ms: int, slippage_pct: float
    ):
        """Execute Kalshi buy with ALL costs"""
        if qty <= 0:
            return
        
        result = await self.execution.execute_kalshi_buy(
            asset, gabagool_price, qty * market_price, latency_ms
        )
        
        if not result.success:
            self.kalshi.rejected_trades += 1
            self.stats['failed'] += 1
            print(f"   ❌ KALSHI: {result.reject_reason}")
            return
        
        self.kalshi.balance -= result.total_cost
        self.kalshi.total_fees_paid += result.trading_fee
        self.kalshi.total_trades += 1
        
        pos = Position(
            market_id=asset,
            title=title,
            side="BUY",
            outcome=outcome,
            slug=slug,
            qty=result.executed_qty,
            entry_price=result.executed_price,
            entry_time=time.time(),
            fees_paid=result.trading_fee,
            slippage_pct=result.slippage_vs_gabagool_pct,
            venue="KALSHI",
            gabagool_price=gabagool_price
        )
        
        self.kalshi.positions[f"{asset[:20]}_{outcome}"] = pos
        self._log_trade(pos, result, result.latency_ms)
        
        print(f"   ✅ KALSHI: {result.executed_qty:.1f} @ ${result.executed_price:.3f}")
        print(f"      Cost: ${result.total_cost:.2f} (fee: ${result.trading_fee:.2f})")
    
    async def _execute_sell(self, asset: str, title: str, latency_ms: int):
        """Execute SELL on both venues"""
        print(f"\n🔴 COPY SELL:")
        print(f"   Gabagool closing: {title[:50]}...")
        
        found_any = False
        for wallet in [self.poly, self.kalshi]:
            # Try multiple matching strategies
            matched_key = None
            
            # Strategy 1: Exact asset prefix match
            for key in list(wallet.positions.keys()):
                if key.startswith(asset[:20]):
                    matched_key = key
                    break
            
            # Strategy 2: Title match (case insensitive)
            if not matched_key and title:
                title_lower = title.lower()[:30]
                for key, pos in wallet.positions.items():
                    if pos.title and title_lower in pos.title.lower():
                        matched_key = key
                        break
            
            # Strategy 3: Market ID contains
            if not matched_key:
                for key in list(wallet.positions.keys()):
                    if asset[:10] in key or key[:10] in asset:
                        matched_key = key
                        break
            
            if not matched_key:
                continue
            
            found_any = True
            pos = wallet.positions[matched_key]
            
            # Get exit price
            if wallet.venue == "POLYMARKET":
                result = await self.execution.execute_polymarket_sell(
                    pos.market_id, pos.qty, latency_ms
                )
            else:
                result = await self.execution.execute_kalshi_sell(
                    pos.market_id, pos.qty, pos.entry_price, latency_ms
                )
            
            if not result.success:
                print(f"   ⚠️ {wallet.venue} SELL failed: {result.reject_reason}")
                continue
            
            # Calculate P&L
            gross_proceeds = result.executed_qty * result.executed_price
            fees = result.trading_fee + result.gas_fee
            net_proceeds = gross_proceeds - fees
            
            pnl = net_proceeds - (pos.qty * pos.entry_price)
            pos.pnl = pnl
            pos.exit_price = result.executed_price
            pos.exit_time = time.time()
            pos.status = "closed"
            
            # Update wallet
            wallet.balance += net_proceeds
            wallet.total_fees_paid += fees
            self.risk.update_daily_pnl(wallet, pnl)
            
            if pnl > 0:
                wallet.wins += 1
            else:
                wallet.losses += 1
            
            wallet.closed_positions.append(pos)
            del wallet.positions[matched_key]
            
            # Log the close
            self._log_close(pos, result)
            
            emoji = "✅" if pnl > 0 else "❌"
            print(f"   {emoji} {wallet.venue}: ${pos.entry_price:.3f} → ${result.executed_price:.3f} = ${pnl:+.2f}")
        
        if not found_any:
            print(f"   ⚠️ No matching position found for: {asset[:30]}...")
    
    def _log_trade(self, pos: Position, result, latency_ms: int):
        """Log trade to file"""
        data = {
            'timestamp': time.time(),
            'venue': pos.venue,
            'market_id': pos.market_id[:30],
            'title': pos.title[:50],
            'side': pos.side,
            'outcome': pos.outcome,
            'qty': round(pos.qty, 3),
            'entry_price': round(pos.entry_price, 4),
            'gabagool_price': round(pos.gabagool_price, 4),
            'slippage_pct': round(pos.slippage_pct * 100, 2),
            'fees_paid': round(pos.fees_paid, 3),
            'total_cost': round(result.total_cost, 2),
            'latency_ms': latency_ms,
            'slug': pos.slug,
            'status': 'open'
        }
        
        with open(self.data_dir / "trades.jsonl", 'ab') as f:
            f.write((json_dumps(data) + '\n').encode())
    
    def _log_close(self, pos: Position, result):
        """Log position close"""
        data = {
            'timestamp': time.time(),
            'venue': pos.venue,
            'market_id': pos.market_id[:30],
            'title': pos.title[:50],
            'side': 'SELL',
            'outcome': pos.outcome,
            'qty': round(pos.qty, 3),
            'entry_price': round(pos.entry_price, 4),
            'exit_price': round(result.executed_price, 4),
            'pnl': round(pos.pnl, 4),
            'fees_paid': round(result.trading_fee + result.gas_fee, 3),
            'slug': pos.slug,
            'status': 'closed'
        }
        
        with open(self.data_dir / "trades.jsonl", 'ab') as f:
            f.write((json_dumps(data) + '\n').encode())
    
    async def _async_save(self):
        """Non-blocking save"""
        try:
            self._save_state()
        except:
            pass
    
    # =========================================================================
    # SETTLEMENT
    # =========================================================================
    
    async def _settlement_loop(self):
        """Settle positions based on market resolution"""
        while self.running:
            try:
                for wallet in [self.poly, self.kalshi]:
                    for key, pos in list(wallet.positions.items()):
                        if pos.age_seconds < 900:  # 15 min
                            continue
                        
                        winner = await self._get_outcome(pos.slug)
                        if not winner:
                            continue
                        
                        won = pos.outcome.lower() == winner.lower() if pos.outcome else False
                        
                        if won:
                            # Win: get $1 per share
                            gross = pos.qty * 1.0
                            
                            # Kalshi takes profit fee
                            if wallet.venue == "KALSHI":
                                profit = pos.qty * (1.0 - pos.entry_price)
                                fee = profit * CONFIG.kalshi_fees.PROFIT_FEE_RATE
                                wallet.total_fees_paid += fee
                                gross -= fee
                            
                            pos.pnl = gross - pos.cost_basis
                            wallet.balance += gross
                            wallet.wins += 1
                        else:
                            # Lose: get $0
                            pos.pnl = -pos.cost_basis
                            wallet.losses += 1
                        
                        pos.status = "settled"
                        pos.exit_price = 1.0 if won else 0.0
                        pos.exit_time = time.time()
                        
                        self.risk.update_daily_pnl(wallet, pos.pnl)
                        wallet.closed_positions.append(pos)
                        del wallet.positions[key]
                        
                        emoji = '✅' if won else '❌'
                        print(f"\n{emoji} SETTLED ({wallet.venue}): {pos.title[:30]}...")
                        print(f"   Entry: ${pos.entry_price:.3f} (gaba: ${pos.gabagool_price:.3f})")
                        print(f"   P&L: ${pos.pnl:+.2f} | Fees: ${pos.fees_paid:.2f} | Slip: {pos.slippage_pct*100:.1f}%")
                
                self._save_state()
                
            except Exception as e:
                pass
            
            await asyncio.sleep(30)
    
    async def _get_outcome(self, slug: str) -> Optional[str]:
        """Get market resolution"""
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
                        
                        prices = market.get('outcomePrices', [])
                        outcomes = market.get('outcomes', [])
                        
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
        """Print status every minute"""
        while self.running:
            await asyncio.sleep(60)
            
            avg_lat = sum(self.stats['latencies']) / max(len(self.stats['latencies']), 1)
            
            print("\n" + "═"*70)
            print(f"📊 PRODUCTION STATUS @ {datetime.now().strftime('%H:%M:%S')}")
            print("═"*70)
            
            for wallet in [self.poly, self.kalshi]:
                pnl = wallet.total_pnl
                pnl_str = f"({pnl:+.2f})" if pnl != 0 else ""
                print(f"   {wallet.venue:12} ${wallet.balance:>7.2f} {pnl_str:>10}")
                print(f"      Positions: {len(wallet.positions):>3} | {wallet.wins}W/{wallet.losses}L ({wallet.win_rate:.0f}%)")
                print(f"      Fees: ${wallet.total_fees_paid:>6.2f} | Slippage: ${wallet.total_slippage_cost:>6.2f}")
            
            print()
            print(f"   Detected: {self.stats['detected']} | Executed: {self.stats['executed']}")
            print(f"   Skipped: {self.stats['skipped_slippage']} (slip) + {self.stats['skipped_risk']} (risk)")
            print(f"   Failed: {self.stats['failed']} | Avg latency: {avg_lat:.0f}ms")
            
            if self.risk.circuit_breaker_triggered:
                print(f"\n   ⚠️ CIRCUIT BREAKER: {self.risk.circuit_breaker_reason}")
            
            print("═"*70)


# =============================================================================
# MAIN
# =============================================================================

async def main():
    trader = ProductionCopyTrader()
    
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(trader.stop()))
    
    await trader.start()


if __name__ == "__main__":
    print("🏛️ Starting Production Copy Trader...")
    asyncio.run(main())

