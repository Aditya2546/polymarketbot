#!/usr/bin/env python3
"""
MASTER BOT RUNNER - Runs all trading bots and settlement with REAL data
"""
import asyncio
import aiohttp
import json
import signal
import sys
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))

from src.logger import setup_logging, StructuredLogger

class MasterBotRunner:
    def __init__(self):
        setup_logging(level="INFO", log_format="text")
        self.logger = StructuredLogger(__name__)
        
        # Gabagool wallet
        self.gabagool_wallet = "0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d"
        
        # Data directories
        self.data_dir = Path("data/fast_copy_gabagool")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # State
        self.running = False
        self.seen_trades = set()
        self.positions = {}
        self.balance = 200.0
        self.total_deployed = 0.0
        
        # Price cache
        self.btc_prices = {}
        self.eth_prices = {}
        
        # Load existing state
        self._load_state()
    
    def _load_state(self):
        """Load existing state from disk"""
        perf_file = self.data_dir / "performance.json"
        if perf_file.exists():
            with open(perf_file) as f:
                state = json.load(f)
            self.balance = state.get('real_balance', state.get('balance', 200.0))
            self.seen_trades = set(state.get('seen_trades', []))
            self.logger.info(f"Loaded state: Balance ${self.balance:.2f}, {len(self.seen_trades)} seen trades")
    
    def _save_state(self):
        """Save state to disk"""
        perf_file = self.data_dir / "performance.json"
        
        existing = {}
        if perf_file.exists():
            with open(perf_file) as f:
                existing = json.load(f)
        
        existing.update({
            'balance': self.balance,
            'seen_trades': list(self.seen_trades),
            'last_update': datetime.now().isoformat(),
            'total_deployed': self.total_deployed
        })
        
        with open(perf_file, 'w') as f:
            json.dump(existing, f, indent=2)
    
    async def fetch_prices(self):
        """Fetch current and historical prices"""
        async with aiohttp.ClientSession() as session:
            # Current prices
            try:
                async with session.get('https://api.coinbase.com/v2/prices/BTC-USD/spot', timeout=5) as r:
                    data = await r.json()
                    btc_current = float(data['data']['amount'])
                async with session.get('https://api.coinbase.com/v2/prices/ETH-USD/spot', timeout=5) as r:
                    data = await r.json()
                    eth_current = float(data['data']['amount'])
                return btc_current, eth_current
            except Exception as e:
                self.logger.error(f"Price fetch error: {e}")
                return None, None
    
    async def fetch_historical_prices(self):
        """Fetch historical 1-minute prices from Binance"""
        async with aiohttp.ClientSession() as session:
            try:
                url = "https://api.binance.us/api/v3/klines"
                
                # BTC
                params = {'symbol': 'BTCUSDT', 'interval': '1m', 'limit': 240}
                async with session.get(url, params=params, timeout=15) as r:
                    candles = await r.json()
                for c in candles:
                    ts = int(c[0]) // 1000
                    self.btc_prices[ts] = float(c[4])
                
                # ETH
                params['symbol'] = 'ETHUSDT'
                async with session.get(url, params=params, timeout=15) as r:
                    candles = await r.json()
                for c in candles:
                    ts = int(c[0]) // 1000
                    self.eth_prices[ts] = float(c[4])
                
                self.logger.info(f"✓ Price data: {len(self.btc_prices)} BTC, {len(self.eth_prices)} ETH points")
            except Exception as e:
                self.logger.error(f"Historical price fetch error: {e}")
    
    async def fetch_gabagool_trades(self):
        """Fetch latest trades from gabagool"""
        async with aiohttp.ClientSession() as session:
            url = f"https://data-api.polymarket.com/trades?user={self.gabagool_wallet}&limit=50"
            try:
                async with session.get(url, timeout=10) as r:
                    if r.status == 200:
                        return await r.json()
            except Exception as e:
                self.logger.error(f"Trade fetch error: {e}")
        return []
    
    async def process_trade(self, trade: dict):
        """Process a single trade from gabagool"""
        title = trade.get('title', '')
        
        # Only crypto 15-min markets
        if 'Up or Down' not in title:
            return
        if 'January 7' not in title:
            return
        
        # Create unique trade ID using transaction hash
        tx_hash = trade.get('transactionHash', '')
        trade_id = tx_hash if tx_hash else f"{trade.get('timestamp', '')}_{trade.get('asset', '')}"
        if trade_id in self.seen_trades:
            return
        
        self.seen_trades.add(trade_id)
        
        # Extract trade details
        outcome = trade.get('outcome', '')
        gab_size = float(trade.get('size', 0))
        price = float(trade.get('price', 0.5))
        
        # Calculate our position (scaled down)
        our_size = min(gab_size * 0.5, 15.0, self.balance * 0.15)
        our_size = max(our_size, 2.0)
        
        if our_size > self.balance:
            self.logger.warning(f"⚠️ Insufficient balance: ${self.balance:.2f}")
            return
        
        # Record trade
        trade_record = {
            'timestamp': datetime.now().isoformat(),
            'market_title': title,
            'outcome': outcome,
            'size': our_size,
            'entry_price': price,
            'gabagool_size': gab_size,
            'status': 'open'
        }
        
        # Save to file
        trades_file = self.data_dir / "trades.jsonl"
        with open(trades_file, 'a') as f:
            f.write(json.dumps(trade_record) + '\n')
        
        # Update balance
        self.balance -= our_size
        self.total_deployed += our_size
        self._save_state()
        
        is_btc = 'Bitcoin' in title
        asset = "BTC" if is_btc else "ETH"
        
        self.logger.info(f"")
        self.logger.info(f"🎯 {'='*66}")
        self.logger.info(f"   COPIED TRADE: {asset} {'UP' if 'Up' in outcome else 'DOWN'}")
        self.logger.info(f"   Size: ${our_size:.2f} @ {price:.3f}")
        self.logger.info(f"   Balance: ${self.balance:.2f}")
        self.logger.info(f"{'='*70}")
    
    def determine_outcome(self, asset: str, start_ts: int, end_ts: int) -> str:
        """Determine real outcome from price data"""
        prices = self.btc_prices if asset == "BTC" else self.eth_prices
        
        start_price = None
        end_price = None
        
        for offset in range(0, 180, 60):
            if start_price is None and (start_ts + offset) in prices:
                start_price = prices[start_ts + offset]
            if end_price is None and (end_ts + offset) in prices:
                end_price = prices[end_ts + offset]
        
        if start_price and end_price:
            return "UP" if end_price > start_price else "DOWN"
        return None
    
    async def settle_trades(self):
        """Settle completed trades using real prices"""
        trades_file = self.data_dir / "trades.jsonl"
        if not trades_file.exists():
            return
        
        # Refresh price data
        await self.fetch_historical_prices()
        
        # Load all trades
        trades = []
        with open(trades_file) as f:
            for line in f:
                trades.append(json.loads(line))
        
        # Group by market
        markets = defaultdict(lambda: {
            'up_cost': 0, 'down_cost': 0,
            'up_shares': 0, 'down_shares': 0
        })
        
        for t in trades:
            title = t.get('market_title', '')
            outcome = t.get('outcome', '')
            size = t.get('size', 0)
            entry = t.get('entry_price', 0.5)
            shares = size / entry if entry > 0 else 0
            
            if 'Up' in outcome:
                markets[title]['up_cost'] += size
                markets[title]['up_shares'] += shares
            else:
                markets[title]['down_cost'] += size
                markets[title]['down_shares'] += shares
        
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        total_pnl = 0
        total_cost = 0
        wins = 0
        losses = 0
        
        self.logger.info(f"\n{'='*70}")
        self.logger.info(f"📊 SETTLEMENT CHECK (Real Prices)")
        self.logger.info(f"{'='*70}\n")
        
        import re
        for title, data in sorted(markets.items()):
            is_btc = 'Bitcoin' in title
            asset = "BTC" if is_btc else "ETH"
            
            up_cost = data['up_cost']
            down_cost = data['down_cost']
            up_shares = data['up_shares']
            down_shares = data['down_shares']
            cost = up_cost + down_cost
            
            if cost == 0:
                continue
            
            total_cost += cost
            
            # Parse time
            time_str = title.split(' - ')[-1].replace('January 7, ', '').strip()
            
            # Parse start/end times
            range_match = re.search(r'(\d{1,2}):?(\d{2})?(PM|AM)-(\d{1,2}):?(\d{2})?(PM|AM)', time_str)
            single_match = re.search(r'(\d{1,2}):?(\d{2})?(PM|AM)', time_str)
            
            start_ts = None
            end_ts = None
            
            if range_match:
                start_h = int(range_match.group(1))
                start_m = int(range_match.group(2) or 0)
                if range_match.group(3) == 'PM' and start_h != 12:
                    start_h += 12
                end_h = int(range_match.group(4))
                end_m = int(range_match.group(5) or 0)
                if range_match.group(6) == 'PM' and end_h != 12:
                    end_h += 12
                
                start_time = today.replace(hour=start_h - 3, minute=start_m)
                end_time = today.replace(hour=end_h - 3, minute=end_m)
                start_ts = int(start_time.timestamp())
                end_ts = int(end_time.timestamp())
            elif single_match:
                h = int(single_match.group(1))
                m = int(single_match.group(2) or 0)
                if single_match.group(3) == 'PM' and h != 12:
                    h += 12
                start_time = today.replace(hour=h - 3, minute=m)
                end_time = start_time + timedelta(minutes=15)
                start_ts = int(start_time.timestamp())
                end_ts = int(end_time.timestamp())
            
            # Get real outcome
            real_outcome = self.determine_outcome(asset, start_ts, end_ts) if start_ts else None
            
            if real_outcome:
                if real_outcome == "UP":
                    payout = up_shares * 1.0
                else:
                    payout = down_shares * 1.0
                
                pnl = payout - cost
                total_pnl += pnl
                
                if pnl > 0:
                    wins += 1
                    status = "✅"
                else:
                    losses += 1
                    status = "❌"
                
                self.logger.info(f"{status} {asset} {time_str[:20]:>20} | {real_outcome:4} | P&L: ${pnl:+.2f}")
            else:
                self.logger.info(f"⏳ {asset} {time_str[:20]:>20} | Pending...")
        
        self.logger.info(f"\n{'─'*70}")
        self.logger.info(f"Total P&L: ${total_pnl:+.2f} | Balance: ${200 + total_pnl:.2f}")
        self.logger.info(f"Win Rate: {wins}/{wins+losses} ({wins/(wins+losses)*100:.0f}%)" if wins+losses > 0 else "")
        self.logger.info(f"{'─'*70}\n")
        
        # Update performance
        perf_file = self.data_dir / "performance.json"
        existing = {}
        if perf_file.exists():
            with open(perf_file) as f:
                existing = json.load(f)
        
        existing['real_pnl'] = total_pnl
        existing['real_balance'] = 200 + total_pnl
        existing['real_wins'] = wins
        existing['real_losses'] = losses
        existing['settlement_time'] = datetime.now().isoformat()
        
        with open(perf_file, 'w') as f:
            json.dump(existing, f, indent=2)
    
    async def run(self):
        """Main bot loop"""
        self.running = True
        
        self.logger.info("=" * 70)
        self.logger.info("🤖 MASTER BOT RUNNER - ALL REAL DATA")
        self.logger.info("=" * 70)
        self.logger.info(f"Time: {datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')}")
        self.logger.info(f"Starting Balance: ${self.balance:.2f}")
        self.logger.info(f"Tracking: @gabagool22")
        self.logger.info("=" * 70)
        self.logger.info("")
        
        # Get initial prices
        btc, eth = await self.fetch_prices()
        if btc and eth:
            self.logger.info(f"📈 BTC: ${btc:,.2f} | ETH: ${eth:,.2f}")
        
        await self.fetch_historical_prices()
        
        self.logger.info("")
        self.logger.info("🟢 LIVE - Watching for trades...")
        self.logger.info("")
        
        last_settlement = 0
        iteration = 0
        
        while self.running:
            iteration += 1
            
            try:
                # Fetch and process new trades
                trades = await self.fetch_gabagool_trades()
                crypto_trades = [t for t in trades if 'Up or Down' in t.get('title', '')]
                
                for trade in crypto_trades:
                    await self.process_trade(trade)
                
                # Run settlement every 5 minutes
                if iteration - last_settlement >= 150:  # 5 min at 2s interval
                    await self.settle_trades()
                    last_settlement = iteration
                
                # Status update every minute
                if iteration % 30 == 0:
                    btc, eth = await self.fetch_prices()
                    if btc:
                        self.logger.info(f"📊 BTC: ${btc:,.2f} | ETH: ${eth:,.2f} | Balance: ${self.balance:.2f} | Trades: {len(self.seen_trades)}")
                
                await asyncio.sleep(2)
                
            except Exception as e:
                self.logger.error(f"Error: {e}")
                await asyncio.sleep(5)
    
    async def stop(self):
        """Stop the bot"""
        self.running = False
        self.logger.info("Stopping bot...")
        self._save_state()
        await self.settle_trades()
        self.logger.info("Bot stopped.")

async def main():
    bot = MasterBotRunner()
    
    def signal_handler(sig, frame):
        print("\n\nShutting down...")
        asyncio.create_task(bot.stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await bot.run()
    except KeyboardInterrupt:
        pass
    finally:
        await bot.stop()

if __name__ == "__main__":
    asyncio.run(main())

