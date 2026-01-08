#!/usr/bin/env python3
"""
🎯 GABAGOOL ARBITRAGE BOT
Implements the REAL Gabagool22 strategy:

1. Buy YES when YES is cheap (oversold)
2. Buy NO when NO is cheap (oversold)  
3. Keep pair_cost = avg_yes + avg_no < $1.00
4. When locked, profit is GUARANTEED regardless of outcome

This is NOT copy trading - this IS the strategy.

Key insight: In a binary market, YES + NO always = $1 at settlement.
If you can buy both for < $1 total, you profit no matter what.

Target: 2-5% per 15-minute market × many markets = massive returns
"""
import asyncio
import aiohttp
import json
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List, Set, Tuple
from dataclasses import dataclass, field

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
except ImportError:
    def json_loads(s): return json.loads(s)
    def json_dumps(o): return json.dumps(o)

sys.path.insert(0, str(Path(__file__).parent))
from src.arbitrage.pair_tracker import PairTracker, PairPosition


# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass
class Config:
    """Arbitrage bot configuration"""
    # Capital
    STARTING_BALANCE: float = 200.0
    MAX_PER_MARKET: float = 50.0  # Max to deploy per market
    MIN_TRADE_SIZE: float = 2.0
    
    # Strategy params
    TARGET_PAIR_COST: float = 0.98  # Lock profit at 2% margin
    MAX_PAIR_COST: float = 0.995    # Never exceed this
    
    # Price thresholds - when to buy
    ATTRACTIVE_PRICE: float = 0.45   # Very attractive buy
    ACCEPTABLE_PRICE: float = 0.55   # Acceptable buy
    
    # Balance limits
    MAX_IMBALANCE_RATIO: float = 2.0  # Max YES/NO ratio before stopping
    
    # Fees
    TAKER_FEE: float = 0.02  # 2%
    GAS_FEE: float = 0.05
    
    # Timing
    POLL_INTERVAL: float = 0.5  # 500ms
    STATUS_INTERVAL: float = 30.0


CONFIG = Config()


# ============================================================================
# MARKET SCANNER
# ============================================================================

@dataclass
class MarketOpportunity:
    """A detected arbitrage opportunity"""
    market_id: str
    title: str
    slug: str
    yes_token: str
    no_token: str
    
    yes_price: float  # Current best ask for YES
    no_price: float   # Current best ask for NO
    
    yes_liquidity: float
    no_liquidity: float
    
    combined_cost: float  # yes_price + no_price
    spread: float  # How far from $1
    
    end_time: Optional[datetime] = None
    
    @property
    def is_arbitrageable(self) -> bool:
        """Can we profitably buy both sides?"""
        return self.combined_cost < CONFIG.MAX_PAIR_COST
    
    @property
    def profit_potential_pct(self) -> float:
        """Potential profit if we buy at these prices"""
        if self.combined_cost >= 1.0:
            return 0
        return ((1.0 - self.combined_cost) / self.combined_cost) * 100
    
    @property
    def cheaper_side(self) -> Tuple[str, float]:
        """Which side is cheaper and by how much"""
        if self.yes_price < self.no_price:
            return ("YES", self.yes_price)
        return ("NO", self.no_price)


class MarketScanner:
    """
    Scans Polymarket for 15-minute crypto markets
    Identifies arbitrage opportunities
    
    Strategy: Use data-api trades to find active 15-min markets,
    then get orderbook prices from CLOB API
    """
    
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self.market_cache: Dict[str, MarketOpportunity] = {}
        self.last_scan = 0
    
    async def scan_markets(self) -> List[MarketOpportunity]:
        """Scan for active 15-minute crypto markets via recent trades"""
        opportunities = []
        
        try:
            # Get recent trades to find active 15-min markets
            url = "https://data-api.polymarket.com/trades"
            params = {"limit": 200}
            
            async with self.session.get(url, params=params) as resp:
                if resp.status != 200:
                    return opportunities
                
                trades = await resp.json()
                
                # Group trades by market to find YES/NO pairs
                market_tokens = {}  # title -> {yes_asset, no_asset}
                
                for t in trades:
                    title = t.get('title', '')
                    if 'up or down' not in title.lower():
                        continue
                    
                    outcome = t.get('outcome', '').lower()
                    asset = t.get('asset', '')
                    slug = t.get('slug', '')
                    
                    if title not in market_tokens:
                        market_tokens[title] = {
                            'yes_asset': None, 
                            'no_asset': None,
                            'slug': slug
                        }
                    
                    if outcome in ['up', 'yes']:
                        market_tokens[title]['yes_asset'] = asset
                    elif outcome in ['down', 'no']:
                        market_tokens[title]['no_asset'] = asset
                
                # For each complete pair, get orderbook prices
                for title, tokens in market_tokens.items():
                    if tokens['yes_asset'] and tokens['no_asset']:
                        opp = await self._get_opportunity(
                            title, 
                            tokens['yes_asset'], 
                            tokens['no_asset'],
                            tokens['slug']
                        )
                        if opp:
                            opportunities.append(opp)
                            self.market_cache[opp.market_id] = opp
        
        except Exception as e:
            print(f"Scan error: {e}")
        
        return opportunities
    
    async def _get_opportunity(self, title: str, yes_asset: str, no_asset: str, 
                               slug: str) -> Optional[MarketOpportunity]:
        """Get arbitrage opportunity from YES/NO token pair"""
        # Get orderbook prices
        yes_price, yes_liq = await self._get_best_ask(yes_asset)
        no_price, no_liq = await self._get_best_ask(no_asset)
        
        if yes_price is None or no_price is None:
            return None
        
        combined = yes_price + no_price
        
        # Use title hash as market_id since we don't have condition_id
        market_id = title[:50]  # Use title prefix as ID
        
        return MarketOpportunity(
            market_id=market_id,
            title=title,
            slug=slug,
            yes_token=yes_asset,
            no_token=no_asset,
            yes_price=yes_price,
            no_price=no_price,
            yes_liquidity=yes_liq,
            no_liquidity=no_liq,
            combined_cost=combined,
            spread=combined - 1.0
        )
    
    async def _get_best_ask(self, token_id: str) -> Tuple[Optional[float], float]:
        """Get best ask price and liquidity for a token"""
        try:
            url = f"https://clob.polymarket.com/book"
            params = {"token_id": token_id}
            
            async with self.session.get(url, params=params) as resp:
                if resp.status != 200:
                    return None, 0
                
                book = await resp.json()
                asks = book.get('asks', [])
                
                if not asks:
                    return None, 0
                
                # Best ask is lowest price (asks sorted descending usually)
                best_ask = min(float(a.get('price', 1.0)) for a in asks)
                total_liq = sum(float(a.get('size', 0)) for a in asks)
                
                return best_ask, total_liq
        
        except:
            return None, 0
    
    async def get_live_prices(self, market_id: str) -> Tuple[Optional[float], Optional[float]]:
        """Get current YES and NO prices for a specific market"""
        if market_id not in self.market_cache:
            return None, None
        
        opp = self.market_cache[market_id]
        yes_price, _ = await self._get_best_ask(opp.yes_token)
        no_price, _ = await self._get_best_ask(opp.no_token)
        
        return yes_price, no_price


# ============================================================================
# ARBITRAGE ENGINE
# ============================================================================

@dataclass
class Wallet:
    """Trading wallet"""
    balance: float
    starting_balance: float
    total_trades: int = 0
    total_fees: float = 0.0


class GabagoolArbBot:
    """
    The REAL Gabagool strategy bot
    
    Strategy:
    1. Scan for 15-minute crypto markets
    2. Monitor YES and NO prices
    3. Buy whichever side is cheap (< $0.50 ideally)
    4. Build positions until pair_cost < $1.00
    5. Once locked, stop trading that market
    6. Collect guaranteed profit at settlement
    """
    
    def __init__(self):
        self.running = False
        self.session: Optional[aiohttp.ClientSession] = None
        self.scanner: Optional[MarketScanner] = None
        
        # Core state
        self.wallet = Wallet(
            balance=CONFIG.STARTING_BALANCE,
            starting_balance=CONFIG.STARTING_BALANCE
        )
        self.tracker = PairTracker(target_pair_cost=CONFIG.TARGET_PAIR_COST)
        
        # Active markets we're trading
        self.active_markets: Set[str] = set()
        
        # Stats
        self.stats = {
            'opportunities_found': 0,
            'trades_executed': 0,
            'positions_locked': 0,
            'positions_settled': 0,
            'total_profit': 0.0
        }
        
        # Data
        self.data_dir = Path("data/gabagool_arb")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self._load_state()
    
    def _load_state(self):
        """Load saved state"""
        state_file = self.data_dir / "state.json"
        if state_file.exists():
            try:
                with open(state_file) as f:
                    state = json.load(f)
                self.wallet.balance = state.get('balance', CONFIG.STARTING_BALANCE)
                self.stats = state.get('stats', self.stats)
            except:
                pass
    
    def _save_state(self):
        """Save state"""
        state = {
            'balance': self.wallet.balance,
            'stats': self.stats,
            'timestamp': time.time()
        }
        with open(self.data_dir / "state.json", 'w') as f:
            json.dump(state, f, indent=2)
    
    async def start(self):
        """Start the arbitrage bot"""
        print("="*70)
        print("🎯 GABAGOOL ARBITRAGE BOT")
        print("="*70)
        print(f"   Strategy: Asymmetric Hedging Arbitrage")
        print(f"   Target: pair_cost < ${CONFIG.TARGET_PAIR_COST}")
        print(f"   Balance: ${self.wallet.balance:.2f}")
        print(f"   uvloop: {'✅' if UVLOOP else '❌'}")
        print("="*70)
        print()
        print("   HOW IT WORKS:")
        print("   1. Find 15-min crypto markets")
        print("   2. Buy YES when YES is cheap")
        print("   3. Buy NO when NO is cheap")
        print("   4. Once avg_yes + avg_no < $1 = LOCKED PROFIT")
        print("   5. Collect guaranteed profit at settlement")
        print("="*70 + "\n")
        
        self.running = True
        
        # Setup
        connector = aiohttp.TCPConnector(limit=30)
        timeout = aiohttp.ClientTimeout(total=5)
        self.session = aiohttp.ClientSession(connector=connector, timeout=timeout)
        self.scanner = MarketScanner(self.session)
        
        # Run tasks
        tasks = [
            self._scan_loop(),
            self._trade_loop(),
            self._status_loop(),
            self._settlement_loop()
        ]
        
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()
    
    async def stop(self):
        """Shutdown"""
        self.running = False
        self._save_state()
        if self.session:
            await self.session.close()
        print("\n👋 Stopped - state saved")
    
    async def _scan_loop(self):
        """Continuously scan for opportunities"""
        print("🔍 Scanner started")
        scan_count = 0
        
        while self.running:
            try:
                opportunities = await self.scanner.scan_markets()
                scan_count += 1
                
                # Log scan results periodically
                if scan_count % 6 == 1:  # Every 30 seconds
                    arb_count = sum(1 for o in opportunities if o.is_arbitrageable)
                    print(f"\n🔍 Scan #{scan_count}: {len(opportunities)} markets, {arb_count} with arb potential")
                
                for opp in opportunities:
                    # Track ALL markets, not just arb ones
                    if opp.market_id not in self.active_markets:
                        self.active_markets.add(opp.market_id)
                        
                        arb_status = "✅ ARB!" if opp.is_arbitrageable else "❌ No arb"
                        print(f"\n📊 {opp.title[:50]}...")
                        print(f"   YES: ${opp.yes_price:.3f} | NO: ${opp.no_price:.3f} | Sum: ${opp.combined_cost:.3f} {arb_status}")
                        
                        if opp.is_arbitrageable:
                            self.stats['opportunities_found'] += 1
                            print(f"   💰 Potential profit: {opp.profit_potential_pct:.1f}%")
                    
                    # Update existing market prices
                    elif opp.market_id in self.scanner.market_cache:
                        old = self.scanner.market_cache[opp.market_id]
                        # Check if arb status changed
                        if not old.is_arbitrageable and opp.is_arbitrageable:
                            print(f"\n🚨 ARB OPENED: {opp.title[:40]}...")
                            print(f"   YES: ${opp.yes_price:.3f} | NO: ${opp.no_price:.3f} | Sum: ${opp.combined_cost:.3f}")
                            print(f"   💰 Profit: {opp.profit_potential_pct:.1f}%")
                            self.stats['opportunities_found'] += 1
                
                await asyncio.sleep(5)  # Scan every 5 seconds
                
            except Exception as e:
                print(f"Scan error: {e}")
                await asyncio.sleep(5)
    
    async def _trade_loop(self):
        """Main trading loop"""
        print("💹 Trader started")
        
        while self.running:
            try:
                for market_id in list(self.active_markets):
                    await self._evaluate_market(market_id)
                
                await asyncio.sleep(CONFIG.POLL_INTERVAL)
                
            except Exception as e:
                print(f"Trade error: {e}")
                await asyncio.sleep(1)
    
    async def _evaluate_market(self, market_id: str):
        """
        Evaluate and potentially trade a market
        
        GABAGOOL STRATEGY:
        1. If YES + NO < $1, there's arbitrage potential
        2. Buy the CHEAPER side first (lower price = better deal)
        3. Then buy the other side when it dips
        4. Keep pair_cost < $1 at all times
        """
        if market_id not in self.scanner.market_cache:
            return
        
        opp = self.scanner.market_cache[market_id]
        
        # Get current position
        pos = self.tracker.positions.get(market_id)
        
        # If profit locked, skip
        if pos and pos.profit_locked:
            return
        
        # Get live prices
        yes_price, no_price = await self.scanner.get_live_prices(market_id)
        if yes_price is None or no_price is None:
            return
        
        # Update cache
        opp.yes_price = yes_price
        opp.no_price = no_price
        opp.combined_cost = yes_price + no_price
        
        # THE KEY CHECK: Is there arbitrage potential?
        if opp.combined_cost >= 1.0:
            return  # No arb opportunity
        
        # Check if we have capital
        if self.wallet.balance < CONFIG.MIN_TRADE_SIZE * 2:
            return
        
        # STRATEGY: Always buy the cheaper side
        # This naturally builds balanced positions over time
        cheaper_side, cheaper_price = opp.cheaper_side
        
        # Check if we should buy
        should_buy, reason = self.tracker.should_buy(market_id, cheaper_side, cheaper_price)
        
        if should_buy:
            await self._execute_trade(market_id, opp, cheaper_side, cheaper_price)
        else:
            # If we can't buy the cheaper side, try the other side if we need balance
            if pos:
                unhedged_side, unhedged_qty = pos.unhedged_qty
                if unhedged_side != "BALANCED" and unhedged_qty > 5:
                    # Need to balance - buy the other side
                    other_side = "NO" if unhedged_side == "YES" else "YES"
                    other_price = no_price if other_side == "NO" else yes_price
                    
                    should_buy2, reason2 = self.tracker.should_buy(market_id, other_side, other_price)
                    if should_buy2:
                        await self._execute_trade(market_id, opp, other_side, other_price)
    
    async def _execute_trade(self, market_id: str, opp: MarketOpportunity, 
                            side: str, price: float):
        """Execute a trade"""
        # Calculate size
        trade_value = min(CONFIG.MIN_TRADE_SIZE, self.wallet.balance * 0.1)
        if trade_value < 1.0:
            return
        
        qty = trade_value / price
        fees = trade_value * CONFIG.TAKER_FEE + CONFIG.GAS_FEE
        total_cost = trade_value + fees
        
        if total_cost > self.wallet.balance:
            return
        
        # Record trade
        success = self.tracker.record_trade(
            market_id=market_id,
            side=side,
            qty=qty,
            price=price,
            fees=fees,
            title=opp.title,
            slug=opp.slug
        )
        
        if not success:
            return
        
        # Update wallet
        self.wallet.balance -= total_cost
        self.wallet.total_trades += 1
        self.wallet.total_fees += fees
        self.stats['trades_executed'] += 1
        
        # Get updated position
        pos = self.tracker.positions[market_id]
        
        # Log
        status = "🔒 LOCKED!" if pos.profit_locked else f"pair: ${pos.pair_cost:.3f}"
        print(f"\n{'🟢' if side=='YES' else '🔴'} BUY {side}: {qty:.1f} @ ${price:.3f}")
        print(f"   {opp.title[:40]}...")
        print(f"   Position: YES {pos.yes_qty:.1f}@${pos.avg_yes_price:.3f} | NO {pos.no_qty:.1f}@${pos.avg_no_price:.3f}")
        print(f"   Status: {status}")
        
        if pos.profit_locked:
            self.stats['positions_locked'] += 1
            print(f"   💰 GUARANTEED PROFIT: ${pos.guaranteed_profit:.2f} ({pos.profit_pct:.1f}%)")
        
        # Log to file
        self._log_trade(opp, side, qty, price, fees, pos)
        self._save_state()
    
    def _log_trade(self, opp: MarketOpportunity, side: str, qty: float, 
                   price: float, fees: float, pos: PairPosition):
        """Log trade to file"""
        data = {
            'timestamp': time.time(),
            'market_id': opp.market_id[:30],
            'title': opp.title[:50],
            'side': side,
            'qty': round(qty, 3),
            'price': round(price, 4),
            'fees': round(fees, 3),
            'yes_qty': round(pos.yes_qty, 2),
            'yes_avg': round(pos.avg_yes_price, 4),
            'no_qty': round(pos.no_qty, 2),
            'no_avg': round(pos.avg_no_price, 4),
            'pair_cost': round(pos.pair_cost, 4) if pos.pair_cost < 10 else None,
            'locked': pos.profit_locked,
            'locked_profit': round(pos.guaranteed_profit, 2) if pos.profit_locked else 0
        }
        
        with open(self.data_dir / "trades.jsonl", 'a') as f:
            f.write(json.dumps(data) + '\n')
    
    async def _settlement_loop(self):
        """Check for market settlements"""
        while self.running:
            try:
                await asyncio.sleep(60)  # Check every minute
                
                for market_id in list(self.tracker.positions.keys()):
                    outcome = await self._check_market_outcome(market_id)
                    if outcome:
                        profit = self.tracker.settle_market(market_id, outcome)
                        if profit is not None:
                            self.wallet.balance += profit + self.tracker.positions.get(market_id, PairPosition("", "", "")).total_spent
                            self.stats['positions_settled'] += 1
                            self.stats['total_profit'] += profit
                            print(f"\n✅ SETTLED: ${profit:+.2f}")
                            self._save_state()
                
            except Exception as e:
                print(f"Settlement error: {e}")
    
    async def _check_market_outcome(self, market_id: str) -> Optional[str]:
        """Check if market has resolved"""
        try:
            # Try to get market resolution
            url = f"https://gamma-api.polymarket.com/markets/{market_id}"
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                
                if data.get('resolved') or data.get('closed'):
                    # Determine winning side
                    outcome_prices = data.get('outcomePrices', [])
                    if outcome_prices:
                        # Higher price = winning side
                        yes_final = float(outcome_prices[0]) if len(outcome_prices) > 0 else 0
                        if yes_final > 0.5:
                            return "YES"
                        return "NO"
        except:
            pass
        return None
    
    async def _status_loop(self):
        """Print status updates"""
        while self.running:
            await asyncio.sleep(CONFIG.STATUS_INTERVAL)
            
            stats = self.tracker.get_total_stats()
            
            print(f"\n{'='*50}")
            print(f"📊 STATUS UPDATE")
            print(f"{'='*50}")
            print(f"Balance: ${self.wallet.balance:.2f} (started ${self.wallet.starting_balance:.2f})")
            print(f"P&L: ${self.wallet.balance - self.wallet.starting_balance:+.2f}")
            print(f"")
            print(f"Active positions: {stats['active_positions']}")
            print(f"Locked positions: {stats['locked_positions']}")
            print(f"Total deployed: ${stats['total_deployed']:.2f}")
            print(f"Locked profit: ${stats['total_locked_profit']:.2f}")
            print(f"")
            print(f"Trades: {self.stats['trades_executed']}")
            print(f"Fees paid: ${self.wallet.total_fees:.2f}")
            print(f"{'='*50}")
            
            # Print position details
            for summary in self.tracker.get_all_summaries():
                print(f"\n  📈 {summary['market']}")
                print(f"     YES: {summary['yes_qty']} @ ${summary['yes_avg']} | NO: {summary['no_qty']} @ ${summary['no_avg']}")
                print(f"     Pair cost: {summary['pair_cost']} | {summary['status']}")
                if summary['locked_profit'] > 0:
                    print(f"     💰 Locked: ${summary['locked_profit']} ({summary['profit_pct']})")


async def main():
    bot = GabagoolArbBot()
    
    # Handle shutdown
    def signal_handler(sig, frame):
        print("\n🛑 Shutting down...")
        bot.running = False
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    await bot.start()


if __name__ == "__main__":
    print("🎯 Starting Gabagool Arbitrage Bot...")
    asyncio.run(main())

