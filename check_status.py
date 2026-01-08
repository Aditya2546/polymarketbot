#!/usr/bin/env python3
"""Quick status check for all running bots - run anytime!"""

import subprocess
import json
from pathlib import Path
from datetime import datetime

def main():
    print()
    print("═" * 70)
    print("         📊 POLYMARKET BOT - STATUS CHECK")
    print("═" * 70)
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Check processes
    processes = [
        ("@gabagool Polymarket", "run_fast_copy_trader.py"),
        ("@gabagool Kalshi", "run_kalshi_copy_trader.py"),
        ("@DrPufferfish Sports", "run_fast_copy_drpufferfish.py"),
        ("Auto Settler", "auto_settler.py"),
    ]
    
    print("━" * 70)
    print("🤖 BOTS:")
    print("━" * 70)
    
    for name, script in processes:
        result = subprocess.run(['pgrep', '-f', script], capture_output=True, text=True)
        status = "🟢" if result.stdout.strip() else "🔴"
        print(f"   {status} {name}")
    
    # Check balances
    print()
    print("━" * 70)
    print("💰 BALANCES:")
    print("━" * 70)
    
    trackers = [
        ("@gabagool (Poly)", "data/fast_copy_gabagool", 200),
        ("@gabagool (Kalshi)", "data/kalshi_copy_gabagool", 200),
        ("@DrPufferfish", "data/fast_copy_drpufferfish", 200),
    ]
    
    total_start = 0
    total_current = 0
    
    for name, data_dir, start in trackers:
        perf_file = Path(data_dir) / "performance.json"
        trades_file = Path(data_dir) / "trades.jsonl"
        
        balance = start
        trades = 0
        pnl = 0
        
        if perf_file.exists():
            with open(perf_file) as f:
                perf = json.load(f)
                balance = perf.get('balance', start)
                pnl = perf.get('realized_pnl', 0)
        
        if trades_file.exists():
            with open(trades_file) as f:
                trades = sum(1 for _ in f)
        
        total_start += start
        total_current += balance
        
        pnl_str = f"${pnl:+.2f}" if pnl != 0 else "pending"
        print(f"   {name:20} ${balance:>8.2f}  ({trades} trades, P&L: {pnl_str})")
    
    print()
    print(f"   {'─' * 50}")
    total_pnl = total_current - total_start
    print(f"   {'TOTAL':20} ${total_current:>8.2f}  (Started: ${total_start:.2f}, P&L: ${total_pnl:+.2f})")
    
    print()
    print("═" * 70)
    print("   Run 'python check_status.py' anytime to check progress!")
    print("═" * 70)
    print()

if __name__ == "__main__":
    main()

