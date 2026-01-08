#!/bin/bash
# Start the dual strategy trading system

cd "$(dirname "$0")"

echo "════════════════════════════════════════════════════════════════════════════════"
echo "              🚀 DUAL STRATEGY LIVE TRADING SYSTEM 🚀"
echo "════════════════════════════════════════════════════════════════════════════════"
echo ""
echo "Running TWO strategies in parallel:"
echo ""
echo "  Strategy 1: Momentum + Mean Reversion Hybrid"
echo "    • Your original prediction model"
echo "    • Combines momentum, mean reversion, volatility"
echo "    • Starting balance: \$200"
echo ""
echo "  Strategy 2: Momentum Follower (10-minute)"
echo "    • Waits 10 minutes into each 15-min interval"
echo "    • Bets on continuation in current direction"
echo "    • \"Follow the trend\" approach"
echo "    • Starting balance: \$200"
echo ""
echo "Both strategies:"
echo "  • Use LIVE Bitcoin data from Coinbase"
echo "  • Track separately to data/strategy1_hybrid/ and data/strategy2_momentum/"
echo "  • Compare performance in real-time"
echo ""
echo "⚠️  PAPER TRADING MODE: No real money at risk"
echo ""
echo "Press Ctrl+C to stop and see which strategy wins!"
echo ""
echo "════════════════════════════════════════════════════════════════════════════════"
echo ""

# Activate venv
source venv/bin/activate

# Run the dual strategy system
python run_dual_strategy.py 2>&1 | tee logs/dual_strategy_$(date +%Y%m%d_%H%M%S).log

