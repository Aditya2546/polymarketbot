#!/usr/bin/env python3
"""
REAL PRICE SETTLER - Uses actual BTC/ETH prices from Binance to determine outcomes
"""
import asyncio
import aiohttp
import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta
from src.logger import setup_logging, StructuredLogger

class RealPriceSettler:
    def __init__(self):
        setup_logging(level="INFO", log_format="text")
        self.logger = StructuredLogger(__name__)
        self.btc_prices = {}  # timestamp -> price
        self.eth_prices = {}
        
    async def fetch_historical_prices(self):
        """Fetch 4 hours of 1-minute price data from Binance"""
        self.logger.info("Fetching historical prices from Binance...")
        
        async with aiohttp.ClientSession() as session:
            # BTC
            url = "https://api.binance.us/api/v3/klines"
            params = {'symbol': 'BTCUSDT', 'interval': '1m', 'limit': 240}
            
            try:
                async with session.get(url, params=params, timeout=15) as r:
                    btc_candles = await r.json()
                for c in btc_candles:
                    ts = int(c[0]) // 1000
                    self.btc_prices[ts] = float(c[4])
                self.logger.info(f"✓ Got {len(btc_candles)} BTC price points")
            except Exception as e:
                self.logger.error(f"BTC fetch error: {e}")
            
            # ETH
            params['symbol'] = 'ETHUSDT'
            try:
                async with session.get(url, params=params, timeout=15) as r:
                    eth_candles = await r.json()
                for c in eth_candles:
                    ts = int(c[0]) // 1000
                    self.eth_prices[ts] = float(c[4])
                self.logger.info(f"✓ Got {len(eth_candles)} ETH price points")
            except Exception as e:
                self.logger.error(f"ETH fetch error: {e}")
    
    def get_price_at_time(self, asset: str, timestamp: int) -> float:
        """Get price closest to timestamp"""
        prices = self.btc_prices if asset == "BTC" else self.eth_prices
        
        # Find closest timestamp within 2 minutes
        for offset in range(0, 180, 60):
            if (timestamp + offset) in prices:
                return prices[timestamp + offset]
            if (timestamp - offset) in prices:
                return prices[timestamp - offset]
        return None
    
    def determine_outcome(self, asset: str, start_ts: int, end_ts: int) -> str:
        """Determine if price went UP or DOWN in the window"""
        start_price = self.get_price_at_time(asset, start_ts)
        end_price = self.get_price_at_time(asset, end_ts)
        
        if start_price and end_price:
            return "UP" if end_price > start_price else "DOWN"
        return None
    
    async def settle_polymarket_trades(self, data_dir: str = "data/fast_copy_gabagool"):
        """Settle all trades using real price data"""
        self.logger.info(f"\n{'='*70}")
        self.logger.info(f"SETTLING TRADES: {data_dir}")
        self.logger.info(f"{'='*70}\n")
        
        trades_file = Path(data_dir) / "trades.jsonl"
        if not trades_file.exists():
            self.logger.warning(f"No trades file found: {trades_file}")
            return
        
        # Load trades
        trades = []
        with open(trades_file) as f:
            for line in f:
                trades.append(json.loads(line))
        
        self.logger.info(f"Loaded {len(trades)} trades")
        
        # Group by market
        markets = defaultdict(lambda: {
            'up_cost': 0, 'down_cost': 0,
            'up_shares': 0, 'down_shares': 0,
            'trades': []
        })
        
        for t in trades:
            title = t.get('market_title', '')
            outcome = t.get('outcome', '')
            size = t.get('size', 0)
            entry = t.get('entry_price', t.get('copy_price', 0.5))
            shares = size / entry if entry > 0 else 0
            
            markets[title]['trades'].append(t)
            if 'Up' in outcome:
                markets[title]['up_cost'] += size
                markets[title]['up_shares'] += shares
            else:
                markets[title]['down_cost'] += size
                markets[title]['down_shares'] += shares
        
        # Process each market
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        results = []
        total_pnl = 0
        total_cost = 0
        wins = 0
        losses = 0
        
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
            
            # Parse time from title
            # Format: "Bitcoin Up or Down - January 7, 4:45PM-5:00PM"
            time_str = title.split(' - ')[-1].replace('January 7, ', '').strip()
            
            # Determine start/end times
            start_ts = None
            end_ts = None
            
            import re
            # Try range format: "4:45PM-5:00PM"
            range_match = re.search(r'(\d{1,2}):?(\d{2})?(PM|AM)-(\d{1,2}):?(\d{2})?(PM|AM)', time_str)
            # Try single time: "5PM ET"
            single_match = re.search(r'(\d{1,2}):?(\d{2})?(PM|AM)', time_str)
            
            if range_match:
                start_h = int(range_match.group(1))
                start_m = int(range_match.group(2) or 0)
                start_ampm = range_match.group(3)
                end_h = int(range_match.group(4))
                end_m = int(range_match.group(5) or 0)
                end_ampm = range_match.group(6)
                
                if start_ampm == 'PM' and start_h != 12:
                    start_h += 12
                if end_ampm == 'PM' and end_h != 12:
                    end_h += 12
                
                # Convert ET to local (PT = ET - 3)
                start_h_local = start_h - 3
                end_h_local = end_h - 3
                
                start_time = today.replace(hour=start_h_local, minute=start_m)
                end_time = today.replace(hour=end_h_local, minute=end_m)
                start_ts = int(start_time.timestamp())
                end_ts = int(end_time.timestamp())
                
            elif single_match:
                h = int(single_match.group(1))
                m = int(single_match.group(2) or 0)
                ampm = single_match.group(3)
                
                if ampm == 'PM' and h != 12:
                    h += 12
                
                h_local = h - 3
                start_time = today.replace(hour=h_local, minute=m)
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
                    status = "✅ WON"
                else:
                    losses += 1
                    status = "❌ LOST"
                
                self.logger.info(f"{status} {asset} {time_str[:20]}")
                self.logger.info(f"    UP: ${up_cost:.2f} | DOWN: ${down_cost:.2f}")
                self.logger.info(f"    Outcome: {real_outcome} | P&L: ${pnl:+.2f}")
                
                results.append({
                    'market': title,
                    'asset': asset,
                    'outcome': real_outcome,
                    'pnl': pnl,
                    'cost': cost
                })
            else:
                self.logger.info(f"⏳ PENDING {asset} {time_str[:20]} (no price data)")
        
        # Save results
        results_file = Path(data_dir) / "settlement_results.json"
        with open(results_file, 'w') as f:
            json.dump({
                'timestamp': datetime.now().isoformat(),
                'total_cost': total_cost,
                'total_pnl': total_pnl,
                'wins': wins,
                'losses': losses,
                'win_rate': wins / (wins + losses) if (wins + losses) > 0 else 0,
                'markets': results
            }, f, indent=2)
        
        self.logger.info(f"\n{'─'*70}")
        self.logger.info(f"SETTLEMENT SUMMARY")
        self.logger.info(f"{'─'*70}")
        self.logger.info(f"  Total Deployed: ${total_cost:.2f}")
        self.logger.info(f"  Wins: {wins} | Losses: {losses}")
        self.logger.info(f"  Win Rate: {wins/(wins+losses)*100:.0f}%" if wins+losses > 0 else "  Win Rate: N/A")
        self.logger.info(f"  P&L: ${total_pnl:+.2f}")
        self.logger.info(f"  Balance: ${200 + total_pnl:.2f}")
        self.logger.info(f"{'─'*70}\n")
        
        # Update performance file
        perf_file = Path(data_dir) / "performance.json"
        if perf_file.exists():
            with open(perf_file) as f:
                perf = json.load(f)
        else:
            perf = {}
        
        perf['real_pnl'] = total_pnl
        perf['real_balance'] = 200 + total_pnl
        perf['real_wins'] = wins
        perf['real_losses'] = losses
        perf['settlement_time'] = datetime.now().isoformat()
        
        with open(perf_file, 'w') as f:
            json.dump(perf, f, indent=2)
        
        return {'pnl': total_pnl, 'balance': 200 + total_pnl, 'wins': wins, 'losses': losses}

async def main():
    settler = RealPriceSettler()
    
    print("=" * 70)
    print("    🔄 REAL PRICE SETTLEMENT SYSTEM")
    print("=" * 70)
    print(f"    Time: {datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')}")
    print("=" * 70)
    print()
    
    # Fetch prices
    await settler.fetch_historical_prices()
    print()
    
    # Settle all trackers
    trackers = [
        "data/fast_copy_gabagool",
    ]
    
    total_pnl = 0
    for tracker in trackers:
        if Path(tracker).exists():
            result = await settler.settle_polymarket_trades(tracker)
            if result:
                total_pnl += result['pnl']
    
    print("=" * 70)
    print("    💰 FINAL VERIFIED P&L")
    print("=" * 70)
    print(f"    Total P&L: ${total_pnl:+.2f}")
    print(f"    Balance: ${200 + total_pnl:.2f}")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(main())

