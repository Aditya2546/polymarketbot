#!/usr/bin/env python3
"""
Run Gabagool Mirror Bot in SHADOW mode.

Real-time copytrading simulation with live data feeds.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.gabagool_mirror.config import ExecutionMode
from src.gabagool_mirror.engine import GabagoolMirrorEngine
from src.gabagool_mirror.ops.logger import setup_logging


async def main():
    """Run shadow mode."""
    setup_logging(level="INFO", json_output=True)
    
    print("=" * 60)
    print("  GABAGOOL MIRROR BOT - SHADOW MODE")
    print("=" * 60)
    print()
    print("  Mode: Real-time data, simulated execution")
    print("  Tracking: @gabagool22 on Polymarket")
    print("  Simulating: Polymarket (exact) + Kalshi (orderbook)")
    print()
    print("  Press Ctrl+C to stop")
    print("=" * 60)
    print()
    
    engine = GabagoolMirrorEngine(mode=ExecutionMode.SHADOW)
    
    async with engine.running():
        await engine.run_shadow()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown requested...")

