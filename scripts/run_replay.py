#!/usr/bin/env python3
"""
Run Gabagool Mirror Bot replay.

Replay stored signals with varying latencies to analyze performance.
"""

import asyncio
import sys
import json
import csv
from pathlib import Path
from datetime import datetime, timedelta
from typing import List
import argparse

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.gabagool_mirror.config import ExecutionMode
from src.gabagool_mirror.engine import GabagoolMirrorEngine
from src.gabagool_mirror.core.signal import CopySignal
from src.gabagool_mirror.storage.database import Database
from src.gabagool_mirror.storage.repository import Repository
from src.gabagool_mirror.ops.logger import setup_logging


async def load_signals_from_db(days: int) -> List[CopySignal]:
    """Load signals from database for replay."""
    db = Database()
    await db.initialize()
    repo = Repository(db)
    
    # Get signals from last N days
    since_ts = int((datetime.utcnow() - timedelta(days=days)).timestamp() * 1000)
    signals_data = await repo.get_signals_since(since_ts, limit=10000)
    
    await db.close()
    
    signals = []
    for s in signals_data:
        try:
            signals.append(CopySignal(
                signal_id=s.signal_id,
                ts_ms=s.ts_ms,
                source=s.source,
                polymarket_market_id=s.polymarket_market_id,
                polymarket_event_name=s.polymarket_event_name or "",
                polymarket_slug=s.polymarket_slug or "",
                side=s.side,
                action=s.action,
                qty=s.qty,
                price=s.price,
                value_usd=s.value_usd,
                meta=s.meta_json or {}
            ))
        except Exception as e:
            print(f"Error loading signal: {e}")
    
    return signals


async def load_signals_from_jsonl(file_path: str) -> List[CopySignal]:
    """Load signals from JSONL file."""
    signals = []
    
    with open(file_path, 'r') as f:
        for line in f:
            try:
                data = json.loads(line)
                signals.append(CopySignal.from_dict(data))
            except Exception as e:
                print(f"Error parsing line: {e}")
    
    return signals


def export_results_csv(results: dict, output_path: str) -> None:
    """Export replay results to CSV."""
    with open(output_path, 'w', newline='') as f:
        writer = csv.writer(f)
        
        # Header
        writer.writerow([
            "latency_ms", "venue",
            "signals_processed", "signals_filled", "fill_rate",
            "avg_slippage_bps", "total_volume",
            "realized_pnl", "locked_edge"
        ])
        
        for latency, metrics in results.items():
            if latency == "latency_comparison":
                continue
            
            for venue in ["polymarket", "kalshi"]:
                m = metrics.get(venue, {})
                writer.writerow([
                    latency.replace("ms", ""),
                    venue.upper(),
                    m.get("signals_processed", 0),
                    m.get("signals_filled", 0),
                    f"{m.get('fill_rate', 0):.3f}",
                    f"{m.get('avg_slippage_bps', 0):.1f}",
                    f"{m.get('total_volume', 0):.2f}",
                    f"{m.get('total_realized_pnl', 0):.2f}",
                    f"{m.get('total_locked_edge', 0):.2f}"
                ])
    
    print(f"Results exported to: {output_path}")


def print_summary(results: dict) -> None:
    """Print replay summary."""
    print("\n" + "=" * 80)
    print("  REPLAY SUMMARY")
    print("=" * 80)
    
    for latency, metrics in sorted(results.items()):
        if latency == "latency_comparison":
            continue
        
        print(f"\n  {latency}")
        print("  " + "-" * 40)
        
        poly = metrics.get("polymarket", {})
        kalshi = metrics.get("kalshi", {})
        
        print(f"  POLYMARKET (Exact Copy Baseline):")
        print(f"    Signals: {poly.get('signals_processed', 0)}")
        print(f"    Volume: ${poly.get('total_volume', 0):,.2f}")
        print(f"    P&L: ${poly.get('total_realized_pnl', 0):+,.2f}")
        
        print(f"\n  KALSHI (Orderbook Simulation):")
        print(f"    Signals: {kalshi.get('signals_processed', 0)}")
        print(f"    Mapped: {kalshi.get('signals_mapped', 0)}")
        print(f"    Filled: {kalshi.get('signals_filled', 0)} ({kalshi.get('fill_rate', 0):.1%})")
        print(f"    Partial: {kalshi.get('signals_partial', 0)} ({kalshi.get('partial_rate', 0):.1%})")
        print(f"    Missed: {kalshi.get('signals_missed', 0)} ({kalshi.get('miss_rate', 0):.1%})")
        print(f"    Avg Slippage: {kalshi.get('avg_slippage_bps', 0):.1f} bps")
        print(f"    Volume: ${kalshi.get('total_volume', 0):,.2f}")
        print(f"    P&L: ${kalshi.get('total_realized_pnl', 0):+,.2f}")
        print(f"    Locked Edge: ${kalshi.get('total_locked_edge', 0):+,.2f}")
    
    # Latency comparison
    if "latency_comparison" in results:
        print("\n" + "-" * 80)
        print("  LATENCY SENSITIVITY ANALYSIS")
        print("-" * 80)
        
        comp = results["latency_comparison"]
        print(f"\n  {'Latency':>10} | {'Fill Rate':>10} | {'Partial':>10} | {'Missed':>10} | {'Avg Slip':>10}")
        print("  " + "-" * 60)
        
        for lat, m in sorted(comp.items(), key=lambda x: int(x[0].replace("ms", ""))):
            print(f"  {lat:>10} | {m['fill_rate']:>9.1%} | {m['partial_rate']:>9.1%} | {m['miss_rate']:>9.1%} | {m['avg_slippage_bps']:>8.1f}bps")
    
    print("\n" + "=" * 80)


async def main():
    """Run replay."""
    parser = argparse.ArgumentParser(description="Replay gabagool signals")
    parser.add_argument("--days", type=int, default=7, help="Days of history to replay")
    parser.add_argument("--delays", type=str, default="2000,5000,10000", help="Comma-separated latencies in ms")
    parser.add_argument("--input", type=str, help="Input JSONL file (optional)")
    parser.add_argument("--output", type=str, default="replay_results.csv", help="Output CSV file")
    
    args = parser.parse_args()
    
    setup_logging(level="INFO", json_output=False)
    
    print("=" * 60)
    print("  GABAGOOL MIRROR BOT - REPLAY MODE")
    print("=" * 60)
    print()
    
    # Parse latencies
    latencies = [int(x.strip()) for x in args.delays.split(",")]
    print(f"  Testing latencies: {latencies}")
    
    # Load signals
    if args.input:
        print(f"  Loading signals from: {args.input}")
        signals = await load_signals_from_jsonl(args.input)
    else:
        print(f"  Loading signals from last {args.days} days...")
        signals = await load_signals_from_db(args.days)
    
    print(f"  Loaded {len(signals)} signals")
    
    if not signals:
        print("\n  No signals found. Run SHADOW mode first to collect data.")
        return
    
    print()
    
    # Run replay
    engine = GabagoolMirrorEngine(mode=ExecutionMode.SIM)
    
    async with engine.running():
        results = await engine.run_replay(signals, latencies)
    
    # Print summary
    print_summary(results)
    
    # Export CSV
    export_results_csv(results, args.output)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nReplay cancelled...")

