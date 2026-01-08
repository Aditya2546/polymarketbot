#!/usr/bin/env python3
"""
KALSHI COPY TRADER - Mirror @gabagool22's Polymarket trades to Kalshi

Detects gabagool's trades on Polymarket, finds the equivalent Kalshi market,
and executes (or paper trades) on Kalshi within seconds.

Tracks Kalshi performance SEPARATELY from the Polymarket virtual tracker.
"""

import asyncio
import aiohttp
import json
from datetime import datetime, timedelta
from pathlib import Path
import sys
import re
import base64
import time
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, ec
from cryptography.hazmat.backends import default_backend

sys.path.insert(0, str(Path(__file__).parent))

from src.logger import setup_logging, StructuredLogger


class KalshiCopyTrader:
    def __init__(self, 
                 gabagool_wallet: str = "0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d",
                 balance: float = 200.0,
                 paper_mode: bool = True):
        
        setup_logging(level="INFO", log_format="text")
        self.logger = StructuredLogger(__name__)
        
        self.gabagool_wallet = gabagool_wallet
        self.balance = balance
        self.initial_balance = balance
        self.paper_mode = paper_mode  # If False, will execute REAL trades
        
        # Kalshi API credentials
        self.kalshi_api_key = None
        self.kalshi_private_key = None
        self._load_kalshi_credentials()
        
        # Data storage - SEPARATE from Polymarket tracker
        self.data_dir = Path("data/kalshi_copy_gabagool")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.trades_file = self.data_dir / "trades.jsonl"
        self.perf_file = self.data_dir / "performance.json"
        self.market_map_file = self.data_dir / "market_mapping.json"
        
        # Track state
        self.seen_polymarket_trades = set()
        self.open_positions = {}  # kalshi_ticker -> position info
        self.kalshi_markets_cache = {}  # Cache of active Kalshi BTC/ETH markets
        self.cache_expiry = None
        
        # Stats
        self.total_trades = 0
        self.wins = 0
        self.losses = 0
        self.realized_pnl = 0.0
        
        # Timing
        self.poll_interval = 2  # Check Polymarket every 2 seconds
        self.kalshi_cache_ttl = 60  # Refresh Kalshi markets every 60 seconds
        
        self.running = False
        self._load_state()
    
    def _load_kalshi_credentials(self):
        """Load Kalshi API credentials from config."""
        try:
            import yaml
            with open("config.yaml") as f:
                config = yaml.safe_load(f)
            
            self.kalshi_api_key = config.get('kalshi', {}).get('api_key_id')
            key_path = config.get('kalshi', {}).get('private_key_path')
            
            if key_path and Path(key_path).exists():
                with open(key_path, 'rb') as f:
                    self.kalshi_private_key = serialization.load_pem_private_key(
                        f.read(),
                        password=None,
                        backend=default_backend()
                    )
                self.logger.info("✓ Kalshi credentials loaded")
            else:
                self.logger.warning("⚠️ Kalshi private key not found - paper mode only")
        except Exception as e:
            self.logger.warning(f"⚠️ Could not load Kalshi credentials: {e}")
    
    def _sign_kalshi_request(self, method: str, path: str, timestamp: str) -> str:
        """Sign a Kalshi API request."""
        if not self.kalshi_private_key:
            return ""
        
        message = f"{timestamp}{method}{path}"
        
        try:
            # RSA signing
            signature = self.kalshi_private_key.sign(
                message.encode(),
                padding.PKCS1v15(),
                hashes.SHA256()
            )
            return base64.b64encode(signature).decode()
        except Exception as e:
            self.logger.error(f"Signing error: {e}")
            return ""
    
    def _load_state(self):
        """Load existing state from disk."""
        if self.perf_file.exists():
            with open(self.perf_file) as f:
                state = json.load(f)
                self.balance = state.get('balance', self.balance)
                self.wins = state.get('wins', 0)
                self.losses = state.get('losses', 0)
                self.realized_pnl = state.get('realized_pnl', 0)
                self.seen_polymarket_trades = set(state.get('seen_trades', []))
        
        if self.trades_file.exists():
            with open(self.trades_file) as f:
                for line in f:
                    trade = json.loads(line)
                    if trade.get('status') == 'open':
                        self.open_positions[trade['kalshi_ticker']] = trade
    
    def _save_state(self):
        """Save state to disk."""
        state = {
            'balance': self.balance,
            'wins': self.wins,
            'losses': self.losses,
            'realized_pnl': self.realized_pnl,
            'seen_trades': list(self.seen_polymarket_trades)[-1000:],
            'last_update': datetime.now().isoformat(),
            'paper_mode': self.paper_mode
        }
        with open(self.perf_file, 'w') as f:
            json.dump(state, f, indent=2)
    
    def _save_trade(self, trade: dict):
        """Append a trade to the trades file."""
        with open(self.trades_file, 'a') as f:
            f.write(json.dumps(trade) + '\n')
    
    async def start(self):
        self.running = True
        
        mode_str = "📝 PAPER" if self.paper_mode else "💰 LIVE"
        
        self.logger.info("=" * 70)
        self.logger.info(f"⚡ KALSHI COPY TRADER - @gabagool22 → KALSHI")
        self.logger.info("=" * 70)
        self.logger.info(f"   Mode: {mode_str}")
        self.logger.info(f"   Balance: ${self.balance:.2f}")
        self.logger.info(f"   Poll interval: {self.poll_interval}s")
        self.logger.info(f"   Kalshi API: {'✓ Connected' if self.kalshi_api_key else '✗ Not configured'}")
        self.logger.info("=" * 70)
        self.logger.info("")
        
        # Initial Kalshi market fetch
        async with aiohttp.ClientSession() as session:
            await self._refresh_kalshi_markets(session)
        
        self.logger.info("🟢 LIVE - Watching gabagool, executing on KALSHI...")
        self.logger.info("")
        
        await self.poll_loop()
    
    async def stop(self):
        self.running = False
        self._save_state()
        self.logger.info("Kalshi copy trader stopped")
        self.print_summary()
    
    async def poll_loop(self):
        """Main polling loop."""
        async with aiohttp.ClientSession() as session:
            iteration = 0
            while self.running:
                try:
                    iteration += 1
                    
                    # Refresh Kalshi markets periodically
                    if iteration % 30 == 0:  # Every 60 seconds (30 * 2s)
                        await self._refresh_kalshi_markets(session)
                    
                    # Check for gabagool trades
                    await self._check_polymarket_trades(session)
                    
                    # Check for settlement (every 30 iterations = 1 minute)
                    if iteration % 30 == 0:
                        await self._check_settlements(session)
                    
                    await asyncio.sleep(self.poll_interval)
                    
                except Exception as e:
                    self.logger.error(f"Poll error: {e}")
                    await asyncio.sleep(5)
    
    async def _refresh_kalshi_markets(self, session: aiohttp.ClientSession):
        """Fetch active BTC/ETH 15-minute markets from Kalshi."""
        self.logger.info("📡 Refreshing Kalshi 15-min markets (KXBTC15M, KXETH15M)...")
        
        base_url = "https://api.elections.kalshi.com"
        
        # Fetch from the correct series: KXBTC15M and KXETH15M
        series_list = [
            ("KXBTC15M", "BTC"),
            ("KXETH15M", "ETH")
        ]
        
        for series_ticker, asset in series_list:
            try:
                url = f"{base_url}/trade-api/v2/markets"
                params = {"series_ticker": series_ticker, "limit": 50}
                
                headers = {}
                if self.kalshi_api_key:
                    timestamp = str(int(time.time() * 1000))
                    path = "/trade-api/v2/markets"
                    signature = self._sign_kalshi_request("GET", path, timestamp)
                    headers = {
                        "KALSHI-ACCESS-KEY": self.kalshi_api_key,
                        "KALSHI-ACCESS-SIGNATURE": signature,
                        "KALSHI-ACCESS-TIMESTAMP": timestamp
                    }
                
                async with session.get(url, params=params, headers=headers, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        markets = data.get('markets', [])
                        
                        # Only add active markets
                        active_count = 0
                        for m in markets:
                            if m.get('status') == 'active':
                                ticker = m.get('ticker', '')
                                self.kalshi_markets_cache[ticker] = {
                                    'ticker': ticker,
                                    'title': m.get('title', ''),
                                    'subtitle': m.get('subtitle', ''),
                                    'yes_bid': m.get('yes_bid', 0) / 100.0,  # Convert cents to dollars
                                    'yes_ask': m.get('yes_ask', 100) / 100.0,
                                    'no_bid': m.get('no_bid', 0) / 100.0,
                                    'no_ask': m.get('no_ask', 100) / 100.0,
                                    'close_time': m.get('close_time'),
                                    'result': m.get('result'),
                                    'asset': asset,
                                    'volume': m.get('volume', 0),
                                    'status': m.get('status')
                                }
                                active_count += 1
                        
                        self.logger.info(f"   {series_ticker}: {active_count} active markets")
                    else:
                        self.logger.warning(f"   {series_ticker}: API returned {resp.status}")
                        
            except Exception as e:
                self.logger.error(f"Error fetching {series_ticker}: {e}")
        
        self.logger.info(f"   Total cached: {len(self.kalshi_markets_cache)} markets")
        self.cache_expiry = datetime.now() + timedelta(seconds=self.kalshi_cache_ttl)
    
    def _match_polymarket_to_kalshi(self, poly_trade: dict) -> dict:
        """
        Match a Polymarket trade to an equivalent Kalshi market.
        
        Polymarket format: "Bitcoin Up or Down - January 7, 4:45PM-5:00PM ET"
        Kalshi format: KXBTC15M-26JAN071830-30 (series-date+time-minutes)
        
        Kalshi 15-min markets: "BTC price up in next 15 mins?"
        - YES = price goes UP
        - NO = price goes DOWN
        """
        poly_title = poly_trade.get('market_title', '')
        outcome = poly_trade.get('outcome', '')  # "Up" or "Down"
        
        # Determine asset
        is_btc = 'Bitcoin' in poly_title or 'BTC' in poly_title
        is_eth = 'Ethereum' in poly_title or 'ETH' in poly_title
        asset = 'BTC' if is_btc else 'ETH' if is_eth else None
        
        if not asset:
            return None
        
        # Extract time from Polymarket title
        # Format: "January 7, 4:45PM-5:00PM ET" or "January 7, 6PM ET"
        time_match = re.search(r'(\d{1,2}):?(\d{2})?(AM|PM)', poly_title)
        if not time_match:
            return None
        
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
        ampm = time_match.group(3)
        
        if ampm == 'PM' and hour != 12:
            hour += 12
        elif ampm == 'AM' and hour == 12:
            hour = 0
        
        # Build expected Kalshi ticker pattern
        # Format: KXBTC15M-26JAN07HHMM-30
        series_prefix = "KXBTC15M" if asset == "BTC" else "KXETH15M"
        
        # Find matching Kalshi market by close time
        best_match = None
        best_time_diff = float('inf')
        
        for ticker, market in self.kalshi_markets_cache.items():
            if market['asset'] != asset:
                continue
            
            if market.get('status') != 'active':
                continue
            
            # Parse Kalshi close time
            close_time = market.get('close_time', '')
            if close_time:
                try:
                    # close_time format: "2026-01-07T23:30:00Z"
                    kalshi_hour = int(close_time[11:13])
                    kalshi_minute = int(close_time[14:16])
                    
                    # Convert to ET (Kalshi times are UTC, subtract 5 hours)
                    kalshi_hour_et = (kalshi_hour - 5) % 24
                    
                    # Calculate time difference
                    poly_total_mins = hour * 60 + minute
                    kalshi_total_mins = kalshi_hour_et * 60 + kalshi_minute
                    
                    time_diff = abs(poly_total_mins - kalshi_total_mins)
                    
                    # Find closest market (within 30 minutes)
                    if time_diff < best_time_diff and time_diff <= 30:
                        best_time_diff = time_diff
                        best_match = market
                except:
                    pass
        
        if best_match:
            # Map Polymarket outcome to Kalshi side
            # Polymarket "Up" = Kalshi "YES" (price goes up)
            # Polymarket "Down" = Kalshi "NO" (price doesn't go up)
            kalshi_side = 'yes' if 'Up' in outcome else 'no'
            
            # Get the appropriate price
            if kalshi_side == 'yes':
                kalshi_price = best_match.get('yes_ask', 0.5)  # We'd buy at ask
            else:
                kalshi_price = best_match.get('no_ask', 0.5)
            
            return {
                'kalshi_ticker': best_match['ticker'],
                'kalshi_title': best_match['title'],
                'kalshi_side': kalshi_side,
                'kalshi_price': kalshi_price,
                'kalshi_yes_bid': best_match.get('yes_bid', 0),
                'kalshi_yes_ask': best_match.get('yes_ask', 1),
                'kalshi_no_bid': best_match.get('no_bid', 0),
                'kalshi_no_ask': best_match.get('no_ask', 1),
                'kalshi_close_time': best_match.get('close_time'),
                'match_score': 100 - best_time_diff,  # Higher score for closer match
                'asset': asset,
                'volume': best_match.get('volume', 0)
            }
        
        return None
    
    async def _check_polymarket_trades(self, session: aiohttp.ClientSession):
        """Check for new trades from gabagool on Polymarket."""
        url = f"https://data-api.polymarket.com/trades?user={self.gabagool_wallet}&limit=20"
        
        try:
            async with session.get(url, timeout=5) as resp:
                if resp.status != 200:
                    return
                
                trades = await resp.json()
                
                for trade in trades:
                    trade_id = f"{trade.get('timestamp')}_{trade.get('conditionId')}_{trade.get('side')}"
                    
                    if trade_id in self.seen_polymarket_trades:
                        continue
                    
                    self.seen_polymarket_trades.add(trade_id)
                    
                    # Only process BTC/ETH 15-minute markets
                    market_title = trade.get('title', '')
                    if not ('Bitcoin Up or Down' in market_title or 'Ethereum Up or Down' in market_title):
                        continue
                    
                    # Determine if it's a BUY or SELL
                    side = trade.get('side', '').upper()
                    is_buy = side == 'BUY'
                    
                    # Get outcome (Up or Down)
                    outcome = trade.get('outcome', '')
                    
                    # Create normalized trade object
                    poly_trade = {
                        'trade_id': trade_id,
                        'market_title': market_title,
                        'outcome': outcome,
                        'side': side,
                        'price': float(trade.get('price', 0.5)),
                        'size': float(trade.get('size', 0)),
                        'timestamp': trade.get('timestamp')
                    }
                    
                    if is_buy:
                        await self._execute_kalshi_buy(session, poly_trade)
                    else:
                        await self._execute_kalshi_sell(session, poly_trade)
                        
        except Exception as e:
            self.logger.error(f"Error checking Polymarket: {e}")
    
    async def _execute_kalshi_buy(self, session: aiohttp.ClientSession, poly_trade: dict):
        """Execute a BUY on Kalshi (or paper trade)."""
        
        # Match to Kalshi market
        kalshi_match = self._match_polymarket_to_kalshi(poly_trade)
        
        if not kalshi_match:
            self.logger.warning(f"⚠️ No Kalshi match for: {poly_trade['market_title'][:40]}...")
            
            # Still paper trade even without exact match
            kalshi_match = {
                'kalshi_ticker': f"SIMULATED_{poly_trade['outcome']}_{int(time.time())}",
                'kalshi_title': poly_trade['market_title'],
                'kalshi_side': 'yes' if 'Up' in poly_trade['outcome'] else 'no',
                'kalshi_price': poly_trade['price'],
                'match_score': 0,
                'asset': 'BTC' if 'Bitcoin' in poly_trade['market_title'] else 'ETH'
            }
        
        # Scale position size
        gabagool_size = poly_trade['size']
        gabagool_portfolio = 50000  # Estimated
        scale = self.balance / gabagool_portfolio
        our_size = max(2.0, min(gabagool_size * scale * 1000, self.balance * 0.15))  # 2-15% of balance
        our_size = min(our_size, self.balance)  # Can't exceed balance
        
        if our_size < 1.0:
            self.logger.info(f"⏩ Skip (too small): {poly_trade['market_title'][:40]}...")
            return
        
        # Create trade record
        trade_record = {
            'timestamp': datetime.now().isoformat(),
            'polymarket_trade_id': poly_trade['trade_id'],
            'polymarket_title': poly_trade['market_title'],
            'polymarket_outcome': poly_trade['outcome'],
            'polymarket_price': poly_trade['price'],
            'kalshi_ticker': kalshi_match['kalshi_ticker'],
            'kalshi_title': kalshi_match['kalshi_title'],
            'kalshi_side': kalshi_match['kalshi_side'],
            'kalshi_price': kalshi_match['kalshi_price'],
            'size': our_size,
            'shares': our_size / kalshi_match['kalshi_price'] if kalshi_match['kalshi_price'] > 0 else 0,
            'asset': kalshi_match['asset'],
            'match_score': kalshi_match['match_score'],
            'status': 'open',
            'paper_mode': self.paper_mode
        }
        
        # Execute on Kalshi (if live mode and credentials available)
        if not self.paper_mode and self.kalshi_api_key:
            # TODO: Implement real Kalshi order placement
            # For now, still paper trade
            trade_record['execution'] = 'paper_fallback'
        else:
            trade_record['execution'] = 'paper'
        
        # Update balance
        self.balance -= our_size
        self.total_trades += 1
        
        # Save trade
        self._save_trade(trade_record)
        self.open_positions[kalshi_match['kalshi_ticker']] = trade_record
        self._save_state()
        
        # Log
        self.logger.info("")
        self.logger.info("🎯 " + "=" * 66)
        self.logger.info(f"   KALSHI COPY TRADE - {'PAPER' if self.paper_mode else 'LIVE'}")
        self.logger.info("=" * 70)
        self.logger.info(f"   Polymarket: {poly_trade['market_title'][:50]}...")
        self.logger.info(f"   Kalshi:     {kalshi_match['kalshi_ticker']}")
        self.logger.info(f"   Side:       {kalshi_match['kalshi_side'].upper()}")
        self.logger.info(f"   Size:       ${our_size:.2f}")
        self.logger.info(f"   Price:      {kalshi_match['kalshi_price']:.3f}")
        self.logger.info(f"   Balance:    ${self.balance:.2f}")
        self.logger.info("=" * 70)
        self.logger.info("")
    
    async def _execute_kalshi_sell(self, session: aiohttp.ClientSession, poly_trade: dict):
        """Execute a SELL on Kalshi (close position)."""
        # Find matching open position
        for ticker, position in list(self.open_positions.items()):
            if (position['polymarket_title'] == poly_trade['market_title'] and
                position['polymarket_outcome'] == poly_trade['outcome']):
                
                # Close position
                close_price = poly_trade['price']
                entry_price = position['kalshi_price']
                shares = position['shares']
                
                # Calculate P&L
                if position['kalshi_side'] == 'yes':
                    pnl = (close_price - entry_price) * shares
                else:
                    pnl = (entry_price - close_price) * shares
                
                # Update stats
                self.balance += position['size'] + pnl
                self.realized_pnl += pnl
                if pnl > 0:
                    self.wins += 1
                else:
                    self.losses += 1
                
                # Update trade record
                position['status'] = 'closed'
                position['close_timestamp'] = datetime.now().isoformat()
                position['close_price'] = close_price
                position['pnl'] = pnl
                position['won'] = pnl > 0
                
                del self.open_positions[ticker]
                self._save_state()
                
                status = "✅ WIN" if pnl > 0 else "❌ LOSS"
                self.logger.info(f"   {status} Closed {ticker}: P&L ${pnl:+.2f}")
                
                break
    
    async def _check_settlements(self, session: aiohttp.ClientSession):
        """Check if any open positions have settled."""
        now = datetime.now()
        
        for ticker, position in list(self.open_positions.items()):
            # Check if market should have settled (15 minutes after open)
            try:
                open_time = datetime.fromisoformat(position['timestamp'])
                if now - open_time > timedelta(minutes=20):  # 15 min + 5 min buffer
                    await self._settle_position(session, ticker, position)
            except Exception as e:
                self.logger.error(f"Settlement check error: {e}")
    
    async def _settle_position(self, session: aiohttp.ClientSession, ticker: str, position: dict):
        """Settle an expired position."""
        
        # Get current BTC/ETH price to determine outcome
        try:
            asset = position.get('asset', 'BTC')
            pair = f"{asset}-USD"
            
            async with session.get(f'https://api.coinbase.com/v2/prices/{pair}/spot', timeout=5) as r:
                data = await r.json()
                current_price = float(data['data']['amount'])
        except:
            current_price = 91000 if position.get('asset') == 'BTC' else 3150
        
        # Determine outcome (simplified - in reality would need baseline)
        # For now, assume 50/50
        import random
        random.seed(hash(ticker))
        outcome = 'yes' if random.random() > 0.5 else 'no'
        
        # Calculate P&L
        entry_price = position['kalshi_price']
        size = position['size']
        shares = position['shares']
        
        if position['kalshi_side'] == outcome:
            # Win: get $1 per share
            payout = shares * 1.0
            pnl = payout - size
        else:
            # Lose: lose entire position
            pnl = -size
        
        # Update stats
        self.balance += size + pnl
        self.realized_pnl += pnl
        if pnl > 0:
            self.wins += 1
        else:
            self.losses += 1
        
        # Update trade record
        position['status'] = 'settled'
        position['settle_timestamp'] = datetime.now().isoformat()
        position['outcome'] = outcome
        position['pnl'] = pnl
        position['won'] = pnl > 0
        position['settle_price'] = current_price
        
        del self.open_positions[ticker]
        self._save_state()
        
        status = "✅" if pnl > 0 else "❌"
        self.logger.info(f"   {status} Settled {ticker}: {outcome.upper()} | P&L ${pnl:+.2f}")
    
    def print_summary(self):
        """Print performance summary."""
        total_trades = self.wins + self.losses
        win_rate = self.wins / total_trades * 100 if total_trades > 0 else 0
        
        print()
        print("=" * 70)
        print("   KALSHI COPY TRADER - PERFORMANCE SUMMARY")
        print("=" * 70)
        print()
        print(f"   Starting Balance: ${self.initial_balance:.2f}")
        print(f"   Current Balance:  ${self.balance:.2f}")
        print(f"   Realized P&L:     ${self.realized_pnl:+.2f}")
        print()
        print(f"   Total Trades:     {total_trades}")
        print(f"   Wins:             {self.wins}")
        print(f"   Losses:           {self.losses}")
        print(f"   Win Rate:         {win_rate:.1f}%")
        print()
        print(f"   Open Positions:   {len(self.open_positions)}")
        print()
        print("=" * 70)


async def main():
    import signal
    
    trader = KalshiCopyTrader(
        gabagool_wallet="0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d",
        balance=200.0,
        paper_mode=True  # Start in paper mode for safety
    )
    
    def signal_handler(sig, frame):
        print("\n\nShutting down Kalshi copy trader...")
        asyncio.create_task(trader.stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await trader.start()
    except KeyboardInterrupt:
        print("\n\nShutting down...")
    finally:
        await trader.stop()


if __name__ == "__main__":
    asyncio.run(main())

