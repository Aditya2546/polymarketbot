#!/usr/bin/env python3
"""
CHECK RESULTS - Run this when you come back to see your P&L
"""
import json
import asyncio
import aiohttp
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import subprocess
import re

async def main():
    print("=" * 70)
    print("    📊 GABAGOOL COPY TRADING RESULTS")
    print("=" * 70)
    print(f"    Time: {datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')}")
    print("=" * 70)
    print()
    
    # Check if bot is running
    result = subprocess.run(['pgrep', '-f', 'run_all_bots.py'], capture_output=True)
    if result.stdout:
        print("    🟢 BOT STATUS: RUNNING")
    else:
        print("    🔴 BOT STATUS: NOT RUNNING")
    print()
    
    # Get current prices
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get('https://api.coinbase.com/v2/prices/BTC-USD/spot') as r:
                btc = float((await r.json())['data']['amount'])
            async with session.get('https://api.coinbase.com/v2/prices/ETH-USD/spot') as r:
                eth = float((await r.json())['data']['amount'])
            print(f"    📈 CURRENT PRICES: BTC ${btc:,.2f} | ETH ${eth:,.2f}")
        except:
            pass
    print()
    
    # Load performance
    perf_file = Path("data/fast_copy_gabagool/performance.json")
    if perf_file.exists():
        with open(perf_file) as f:
            perf = json.load(f)
        
        balance = perf.get('real_balance', perf.get('balance', 200))
        pnl = perf.get('real_pnl', 0)
        wins = perf.get('real_wins', 0)
        losses = perf.get('real_losses', 0)
        
        print("─" * 70)
        print("    💰 VERIFIED P&L (from real Binance prices)")
        print("─" * 70)
        print(f"    Starting Balance:  $200.00")
        print(f"    Current Balance:   ${balance:.2f}")
        print(f"    P&L:               ${pnl:+.2f}")
        print(f"    Win/Loss:          {wins}W / {losses}L")
        if wins + losses > 0:
            print(f"    Win Rate:          {wins/(wins+losses)*100:.0f}%")
        print()
    
    # Load and show recent trades
    trades_file = Path("data/fast_copy_gabagool/trades.jsonl")
    if trades_file.exists():
        trades = []
        with open(trades_file) as f:
            for line in f:
                trades.append(json.loads(line))
        
        print("─" * 70)
        print(f"    📋 TRADES RECORDED: {len(trades)}")
        print("─" * 70)
        
        # Group by market
        markets = defaultdict(int)
        for t in trades:
            title = t.get('market_title', '')
            short = title.split(' - ')[-1].replace('January 7, ', '') if ' - ' in title else title
            markets[short] += 1
        
        print("    Markets traded:")
        for market, count in sorted(markets.items()):
            print(f"      • {market}: {count} trades")
        print()
    
    # Check latest log
    import glob
    logs = sorted(glob.glob("logs/master_*.log"), reverse=True)
    if logs:
        print("─" * 70)
        print("    📋 LATEST LOG OUTPUT:")
        print("─" * 70)
        with open(logs[0]) as f:
            lines = f.readlines()
        for line in lines[-10:]:
            print(f"    {line.rstrip()}")
        print()
    
    print("=" * 70)
    print("    ✅ All data saved to: data/fast_copy_gabagool/")
    print("    📁 Files: trades.jsonl, performance.json")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(main())

