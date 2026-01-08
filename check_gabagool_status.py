#!/usr/bin/env python3
"""Quick status check for Gabagool Shadow Copy - calculates from trades.jsonl directly."""

import json
from pathlib import Path
from datetime import datetime
import pytz

data_dir = Path("data/gabagool_shadow")

# Get ET time
et = pytz.timezone('America/New_York')
now_et = datetime.now(et)

print("=" * 60)
print("  📊 GABAGOOL SHADOW COPY STATUS")
print("=" * 60)
print(f"  Local: {datetime.now().strftime('%I:%M:%S %p')}")
print(f"  ET:    {now_et.strftime('%I:%M:%S %p ET')}")
print()

# Load all trades and calculate from scratch
trades_file = data_dir / "trades.jsonl"
if not trades_file.exists():
    print("  ⚠️ No trades file found - bot may not be running")
    exit(1)

all_trades = []
with open(trades_file) as f:
    for line in f:
        if line.strip():
            all_trades.append(json.loads(line))

# Separate by venue and status
poly_open = [t for t in all_trades if t.get('venue') == 'POLYMARKET' and t.get('status') == 'open']
poly_settled = [t for t in all_trades if t.get('venue') == 'POLYMARKET' and t.get('status') == 'settled']
poly_closed = [t for t in all_trades if t.get('venue') == 'POLYMARKET' and t.get('status') == 'closed']

kalshi_open = [t for t in all_trades if t.get('venue') == 'KALSHI' and t.get('status') == 'open']
kalshi_settled = [t for t in all_trades if t.get('venue') == 'KALSHI' and t.get('status') == 'settled']
kalshi_closed = [t for t in all_trades if t.get('venue') == 'KALSHI' and t.get('status') == 'closed']

# Calculate P&L
poly_realized_pnl = sum(t.get('pnl', 0) or 0 for t in poly_settled + poly_closed)
kalshi_realized_pnl = sum(t.get('pnl', 0) or 0 for t in kalshi_settled + kalshi_closed)

# Calculate deployed capital
poly_deployed = sum(t.get('qty', 0) * t.get('entry_price', 0) for t in poly_open)
kalshi_deployed = sum(t.get('qty', 0) * t.get('entry_price', 0) for t in kalshi_open)

# Calculate current balance
poly_balance = 200 - poly_deployed + poly_realized_pnl
kalshi_balance = 200 - kalshi_deployed + kalshi_realized_pnl

# Win/loss counts
poly_wins = len([t for t in poly_settled + poly_closed if (t.get('pnl') or 0) > 0])
poly_losses = len([t for t in poly_settled + poly_closed if (t.get('pnl') or 0) <= 0])
kalshi_wins = len([t for t in kalshi_settled + kalshi_closed if (t.get('pnl') or 0) > 0])
kalshi_losses = len([t for t in kalshi_settled + kalshi_closed if (t.get('pnl') or 0) <= 0])

print("  DUAL SIMULATION BALANCES:")
print("  " + "-" * 40)

print(f"  📈 POLYMARKET (Exact Copy):")
print(f"     Balance:    ${poly_balance:.2f}")
print(f"     Deployed:   ${poly_deployed:.2f} ({len(poly_open)} positions)")
print(f"     Realized:   ${poly_realized_pnl:+.2f}")
print(f"     W/L:        {poly_wins}/{poly_losses}")
print()
print(f"  📊 KALSHI (With Slippage):")
print(f"     Balance:    ${kalshi_balance:.2f}")
print(f"     Deployed:   ${kalshi_deployed:.2f} ({len(kalshi_open)} positions)")
print(f"     Realized:   ${kalshi_realized_pnl:+.2f}")
print(f"     W/L:        {kalshi_wins}/{kalshi_losses}")
print()

# Show open positions by market
if poly_open:
    print("  OPEN POSITIONS:")
    print("  " + "-" * 40)
    
    # Group by market title
    markets = {}
    for t in poly_open:
        title = t.get('market_title', '')[:45]
        if title not in markets:
            markets[title] = {'count': 0, 'sides': []}
        markets[title]['count'] += 1
        markets[title]['sides'].append(t.get('side'))
    
    for title, info in list(markets.items())[:5]:
        sides = set(info['sides'])
        sides_str = '/'.join(sides)
        print(f"    {info['count']:2} pos | {sides_str:8} | {title}")
    
    if len(markets) > 5:
        print(f"    ... and {len(markets) - 5} more markets")
    print()

# Show recent settlements
all_settled = poly_settled + poly_closed + kalshi_settled + kalshi_closed
if all_settled:
    print(f"  SETTLEMENTS: {len(all_settled)} trades")
    print("  " + "-" * 40)
    
    # Sort by most recent
    recent = sorted(all_settled, key=lambda x: x.get('entry_time', ''), reverse=True)[:6]
    for t in recent:
        venue = t.get('venue', '?')[:4]
        side = t.get('side', '?')
        pnl = t.get('pnl', 0) or 0
        outcome = t.get('settlement_outcome', t.get('status', '?'))
        emoji = "✅" if pnl > 0 else "❌"
        print(f"    {emoji} [{venue}] {side:4} → {outcome:6} | ${pnl:+.2f}")

print()
print("=" * 60)

# Check if bot is running
import subprocess
result = subprocess.run(['pgrep', '-f', 'gabagool_shadow'], capture_output=True)
if result.returncode == 0:
    print("  ✅ Bot is RUNNING")
else:
    print("  ⚠️ Bot is NOT RUNNING - restart with:")
    print("     python run_gabagool_shadow.py")

print("  📺 Watch live: tail -f logs/gabagool_shadow.log")
print("=" * 60)
