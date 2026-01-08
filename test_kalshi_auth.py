#!/usr/bin/env python3
"""Test Kalshi API authentication."""

import asyncio
import sys
from src.config import get_config
from src.data.kalshi_client import KalshiClient


async def test_authentication():
    """Test Kalshi API authentication and basic functionality."""
    
    print("=" * 60)
    print("Testing Kalshi API Authentication")
    print("=" * 60)
    print()
    
    try:
        # Load config
        print("📋 Loading configuration...")
        config = get_config()
        print(f"   ✓ Config loaded")
        print(f"   API Key ID: {config.kalshi_api_key_id}")
        print(f"   Private Key: {config.kalshi_private_key_path}")
        print()
        
        # Initialize client
        print("🔌 Initializing Kalshi client...")
        client = KalshiClient(
            api_key_id=config.kalshi_api_key_id,
            private_key_path=config.kalshi_private_key_path,
            base_url=config.kalshi_base_url,
            ws_url=config.kalshi_ws_url
        )
        print("   ✓ Client initialized")
        print()
        
        # Test authentication
        print("🔐 Testing authentication...")
        await client.start()
        print("   ✓ Authentication successful!")
        print()
        
        # Test balance retrieval
        print("💰 Fetching account balance...")
        balance = await client.get_balance()
        if balance is not None:
            print(f"   ✓ Balance: ${balance:.2f}")
        else:
            print("   ⚠ Could not fetch balance (may not have permission)")
        print()
        
        # Test market discovery
        print("🔍 Discovering BTC markets...")
        markets = await client.get_markets(status="open")
        print(f"   ✓ Found {len(markets)} open markets")
        
        # Look for BTC 15m markets specifically
        btc_markets = [m for m in markets if "BTC" in m.ticker.upper()]
        if btc_markets:
            print(f"   ✓ Found {len(btc_markets)} BTC markets")
            for market in btc_markets[:3]:  # Show first 3
                print(f"      - {market.ticker}: {market.title}")
        else:
            print("   ⚠ No BTC markets found (may not be active right now)")
        print()
        
        # Test specific BTC 15m market discovery
        print("🎯 Looking for active BTC 15-minute market...")
        btc_15m = await client.discover_active_btc_15m_market()
        if btc_15m:
            print(f"   ✓ Found active market: {btc_15m.ticker}")
            print(f"      Title: {btc_15m.title}")
            print(f"      Status: {btc_15m.status}")
            print(f"      Baseline: ${btc_15m.get_baseline()}")
            print(f"      Mid Price: {btc_15m.get_mid_price()}")
        else:
            print("   ⚠ No active BTC 15-minute market found")
            print("      (Markets may not be active at this time)")
        print()
        
        # Cleanup
        await client.stop()
        
        print("=" * 60)
        print("✅ All tests passed!")
        print("=" * 60)
        print()
        print("Your Kalshi API credentials are configured correctly!")
        print("You're ready to run: python main.py --mode live")
        print()
        
        return True
        
    except Exception as e:
        print()
        print("=" * 60)
        print("❌ Test failed!")
        print("=" * 60)
        print()
        print(f"Error: {e}")
        print()
        print("Troubleshooting:")
        print("1. Verify your API Key ID in config.yaml")
        print("2. Ensure private key file exists and is readable")
        print("3. Check that you have network connectivity")
        print("4. Verify credentials at: https://kalshi.com/account/api")
        print()
        
        import traceback
        traceback.print_exc()
        
        return False


if __name__ == "__main__":
    success = asyncio.run(test_authentication())
    sys.exit(0 if success else 1)

