#!/bin/bash
# Start the copy trading system

cd "$(dirname "$0")"

echo "════════════════════════════════════════════════════════════════════════════════"
echo "                   🎯 COPY TRADING SYSTEM 🎯"
echo "════════════════════════════════════════════════════════════════════════════════"
echo ""
echo "Following Polymarket trader: @gabagool22"
echo "Wallet: 0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d"
echo ""
echo "Profile: https://polymarket.com/@gabagool22"
echo ""
echo "This will:"
echo "  • Track all positions and trades from this wallet"
echo "  • Mirror their trades with a \$200 virtual balance"
echo "  • Scale position sizes proportionally"
echo "  • Track performance separately"
echo ""
echo "Data saved to: data/copy_trading/"
echo ""
echo "⚠️  PAPER TRADING MODE: No real money at risk"
echo ""
echo "Press Ctrl+C to stop at any time"
echo ""
echo "════════════════════════════════════════════════════════════════════════════════"
echo ""

# Activate venv
source venv/bin/activate

# Run the copy trading system
python run_copy_trader.py 2>&1 | tee logs/copy_trading_$(date +%Y%m%d_%H%M%S).log

