#!/usr/bin/env python3
"""Quick status check for Volatility Arb Bot."""

import json
from pathlib import Path
from datetime import datetime

data_dir = Path("data/volatility_arb")

print("=" * 60)
print("  🎰 VOLATILITY ARB STATUS")
print("=" * 60)
print(f"  Time: {datetime.now().strftime('%I:%M:%S %p')}")
print()

# Load state
state_file = data_dir / "state.json"
if state_file.exists():
    with open(state_file) as f:
        state = json.load(f)
    print(f"  Balance: ${state.get('balance', 200):.2f}")
    print(f"  Markets seen: {len(state.get('seen_markets', []))}")
else:
    print("  ⚠️ No state file - bot may not be running")

# Load trades
trades_file = data_dir / "trades.jsonl"
if trades_file.exists():
    trades = []
    with open(trades_file) as f:
        for line in f:
            if line.strip():
                trades.append(json.loads(line))
    
    open_trades = [t for t in trades if t.get('status') == 'open']
    closed_trades = [t for t in trades if t.get('status') == 'closed']
    
    realized_pnl = sum(t.get('pnl', 0) or 0 for t in closed_trades)
    wins = len([t for t in closed_trades if (t.get('pnl') or 0) > 0])
    losses = len([t for t in closed_trades if (t.get('pnl') or 0) <= 0])
    
    print()
    print(f"  Open positions: {len(open_trades)}")
    print(f"  Closed trades:  {len(closed_trades)}")
    print(f"  Realized P&L:   ${realized_pnl:+.2f}")
    print(f"  Win/Loss:       {wins}W / {losses}L")
    
    if closed_trades:
        print()
        print("  Recent Trades:")
        for t in closed_trades[-5:]:
            side = t.get('side', '?')
            entry = t.get('entry_price', 0)
            exit_p = t.get('exit_price', 0)
            pnl = t.get('pnl', 0) or 0
            emoji = "✅" if pnl > 0 else "❌"
            print(f"    {emoji} {side:3} @ ${entry:.2f} → ${exit_p:.2f} | P&L: ${pnl:+.2f}")
else:
    print("  No trades yet")

print()
print("=" * 60)

# Check if running
import subprocess
result = subprocess.run(['pgrep', '-f', 'volatility_arb'], capture_output=True)
if result.returncode == 0:
    print("  ✅ Bot is RUNNING")
else:
    print("  ⚠️ Bot is NOT running")
print("=" * 60)

