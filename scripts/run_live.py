#!/usr/bin/env python3
"""
Run Gabagool Mirror Bot in LIVE mode.

⚠️  DANGER: This mode places real orders on Kalshi.

Prerequisites:
1. Set KALSHI_LIVE_ENABLED=true in environment
2. Ensure Kalshi API credentials are valid
3. Review risk parameters in config
4. Run SHADOW mode first to validate performance
"""

import asyncio
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.gabagool_mirror.config import get_settings, ExecutionMode
from src.gabagool_mirror.engine import GabagoolMirrorEngine
from src.gabagool_mirror.ops.logger import setup_logging


def check_prerequisites() -> bool:
    """Check all prerequisites for live trading."""
    settings = get_settings()
    
    print("=" * 60)
    print("  ⚠️  LIVE TRADING MODE SAFETY CHECK")
    print("=" * 60)
    print()
    
    checks = []
    
    # Check KALSHI_LIVE_ENABLED
    if settings.kalshi_live_enabled:
        checks.append(("KALSHI_LIVE_ENABLED", True, "ENABLED"))
    else:
        checks.append(("KALSHI_LIVE_ENABLED", False, "disabled - set to true in env"))
    
    # Check API credentials
    if settings.kalshi_api_key_id:
        checks.append(("Kalshi API Key", True, f"{settings.kalshi_api_key_id[:8]}..."))
    else:
        checks.append(("Kalshi API Key", False, "missing"))
    
    if settings.kalshi_private_key_path and Path(settings.kalshi_private_key_path).exists():
        checks.append(("Kalshi Private Key", True, "found"))
    else:
        checks.append(("Kalshi Private Key", False, "missing"))
    
    # Check risk limits
    checks.append(("Max Position", True, f"${settings.max_position_usd}"))
    checks.append(("Max Exposure", True, f"${settings.max_total_exposure_usd}"))
    checks.append(("Daily Loss Limit", True, f"${settings.daily_loss_limit_usd}"))
    
    # Print checks
    all_passed = True
    for name, passed, msg in checks:
        status = "✓" if passed else "✗"
        print(f"  {status} {name}: {msg}")
        if not passed:
            all_passed = False
    
    print()
    
    if not all_passed:
        print("  ❌ Prerequisites not met. Cannot proceed with LIVE mode.")
        print()
        print("  To enable live trading:")
        print("    1. Set KALSHI_LIVE_ENABLED=true in .env")
        print("    2. Configure Kalshi API credentials")
        print("    3. Run SHADOW mode first to validate")
        print()
        return False
    
    return True


def get_confirmation() -> bool:
    """Get user confirmation for live trading."""
    print("=" * 60)
    print("  🚨 FINAL CONFIRMATION REQUIRED")
    print("=" * 60)
    print()
    print("  You are about to start LIVE trading.")
    print("  This will place REAL orders on Kalshi.")
    print("  Real money is at risk.")
    print()
    print("  Type 'I UNDERSTAND THE RISKS' to proceed:")
    
    response = input("  > ").strip()
    
    return response == "I UNDERSTAND THE RISKS"


async def main():
    """Run live mode."""
    setup_logging(level="INFO", json_output=True)
    
    # Check prerequisites
    if not check_prerequisites():
        sys.exit(1)
    
    # Get confirmation
    if not get_confirmation():
        print("\n  Live trading cancelled.")
        sys.exit(0)
    
    print()
    print("=" * 60)
    print("  🔴 LIVE TRADING STARTING")
    print("=" * 60)
    print()
    
    engine = GabagoolMirrorEngine(mode=ExecutionMode.LIVE)
    
    async with engine.running():
        await engine.run_shadow()  # Same loop, but with live execution enabled


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nEmergency shutdown...")

