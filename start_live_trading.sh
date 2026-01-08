#!/bin/bash
# Start the live trading system

cd "$(dirname "$0")"

echo "════════════════════════════════════════════════════════════════════════════════"
echo "                    🚀 STARTING LIVE TRADING SYSTEM 🚀"
echo "════════════════════════════════════════════════════════════════════════════════"
echo ""
echo "This will:"
echo "  • Connect to LIVE Bitcoin price feeds (Coinbase/Binance/Kraken)"
echo "  • Monitor BTC price every second"
echo "  • Make predictions on 15-minute direction"
echo "  • Execute trades when edge is detected"
echo "  • Track all trades and performance to disk"
echo ""
echo "⚠️  PAPER TRADING MODE: No real money at risk"
echo ""
echo "Press Ctrl+C to stop at any time"
echo ""
echo "════════════════════════════════════════════════════════════════════════════════"
echo ""

# Activate venv
source venv/bin/activate

# Run the system
python run_live.py 2>&1 | tee logs/live_trading_$(date +%Y%m%d_%H%M%S).log

