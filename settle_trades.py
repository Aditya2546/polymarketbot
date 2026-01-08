#!/usr/bin/env python3
"""
Settle all open trades based on current BTC price.

This script checks all trades that are older than 15 minutes
and settles them based on whether the price went UP or DOWN.
"""

import json
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from src.data.live_btc_feed import LiveBTCFeed


async def get_current_btc_price():
    """Get current BTC price from live feed."""
    feed = LiveBTCFeed()
    await feed.start()
    price = feed.get_current_price()
    await feed.stop()
    return price


def settle_trades_in_file(trades_file: Path, perf_file: Path, current_price: float, strategy_name: str):
    """
    Settle all open trades in a file.
    
    Returns: (settled_count, wins, losses, total_pnl)
    """
    if not trades_file.exists():
        return 0, 0, 0, 0
    
    now = datetime.now()
    all_trades = []
    
    # Read all trades
    with open(trades_file, 'r') as f:
        for line in f:
            try:
                trade = json.loads(line)
                all_trades.append(trade)
            except:
                continue
    
    settled_count = 0
    wins = 0
    losses = 0
    total_pnl = 0
    balance_change = 0
    
    print(f"\n{'='*60}")
    print(f"  {strategy_name}")
    print(f"{'='*60}")
    print(f"  Current BTC Price: ${current_price:,.2f}")
    print(f"  Checking {len(all_trades)} trades...")
    print()
    
    for trade in all_trades:
        if trade.get('status') != 'open':
            continue
        
        # Parse trade timestamp
        try:
            trade_time = datetime.fromisoformat(trade['timestamp'])
        except:
            continue
        
        # Check if 15 minutes have passed
        elapsed = (now - trade_time).total_seconds() / 60
        
        if elapsed >= 15:
            # Time to settle!
            baseline = trade.get('baseline', current_price)
            
            # Determine outcome
            actual_outcome = "YES" if current_price > baseline else "NO"
            
            # Did we win?
            won = (trade['side'] == actual_outcome)
            
            # Calculate P&L
            size = trade['size']
            entry_price = trade['entry_price']
            
            if won:
                payout = size / entry_price
                pnl = payout - size
                wins += 1
            else:
                pnl = -size
                payout = 0
                losses += 1
            
            # Update trade
            trade['status'] = 'closed'
            trade['outcome'] = actual_outcome
            trade['pnl'] = pnl
            trade['close_timestamp'] = now.isoformat()
            trade['final_price'] = current_price
            trade['won'] = won
            
            balance_change += payout
            total_pnl += pnl
            settled_count += 1
            
            result = "✅ WON" if won else "❌ LOST"
            print(f"  {result}: {trade['side']:3} @ {entry_price:.3f} → {actual_outcome} | "
                  f"Baseline: ${baseline:,.2f} | P&L: ${pnl:+.2f}")
    
    # Rewrite trades file
    if settled_count > 0:
        with open(trades_file, 'w') as f:
            for trade in all_trades:
                f.write(json.dumps(trade) + '\n')
        
        # Update performance
        if perf_file.exists():
            with open(perf_file, 'r') as f:
                perf = json.load(f)
            
            perf['balance'] = perf.get('balance', 0) + balance_change
            if perf['balance'] > perf.get('peak_balance', 0):
                perf['peak_balance'] = perf['balance']
            perf['last_update'] = now.isoformat()
            
            with open(perf_file, 'w') as f:
                json.dump(perf, f, indent=2)
    
    print()
    print(f"  Settled: {settled_count} trades")
    print(f"  Wins: {wins}, Losses: {losses}")
    if settled_count > 0:
        print(f"  Win Rate: {wins/settled_count*100:.1f}%")
    print(f"  Total P&L: ${total_pnl:+.2f}")
    
    return settled_count, wins, losses, total_pnl


async def main():
    print("═"*60)
    print("           💵 SETTLING ALL OPEN TRADES")
    print("═"*60)
    
    # Get current BTC price
    print("\n📡 Fetching current BTC price...")
    try:
        current_price = await get_current_btc_price()
        print(f"   Current BTC: ${current_price:,.2f}")
    except Exception as e:
        print(f"   Error getting price: {e}")
        print("   Using fallback price estimation...")
        current_price = 91000  # Fallback
    
    # Settle each strategy
    strategies = [
        ("Strategy 1 (Hybrid)", 
         Path("data/strategy1_hybrid/trades.jsonl"),
         Path("data/strategy1_hybrid/performance.json")),
        ("Strategy 2 (Momentum 10min)", 
         Path("data/strategy2_momentum/trades.jsonl"),
         Path("data/strategy2_momentum/performance.json")),
    ]
    
    total_settled = 0
    total_wins = 0
    total_losses = 0
    total_pnl = 0
    
    for name, trades_file, perf_file in strategies:
        s, w, l, p = settle_trades_in_file(trades_file, perf_file, current_price, name)
        total_settled += s
        total_wins += w
        total_losses += l
        total_pnl += p
    
    # Print summary
    print()
    print("═"*60)
    print("           📊 SETTLEMENT SUMMARY")
    print("═"*60)
    print()
    print(f"  Total Trades Settled: {total_settled}")
    print(f"  Total Wins:           {total_wins}")
    print(f"  Total Losses:         {total_losses}")
    if total_settled > 0:
        print(f"  Overall Win Rate:     {total_wins/total_settled*100:.1f}%")
    print(f"  ─────────────────────────────")
    print(f"  TOTAL P&L:            ${total_pnl:+.2f}")
    print()
    
    # Show updated balances
    print("💰 UPDATED BALANCES:")
    print("-"*60)
    for name, _, perf_file in strategies:
        if perf_file.exists():
            with open(perf_file, 'r') as f:
                perf = json.load(f)
            print(f"  {name}: ${perf['balance']:.2f}")
    print()
    print("═"*60)


if __name__ == "__main__":
    asyncio.run(main())

