#!/bin/bash
# Monitor live trading activity

echo "════════════════════════════════════════════════════════════════════════════════"
echo "                     📊 LIVE TRADING MONITOR 📊"
echo "════════════════════════════════════════════════════════════════════════════════"
echo ""
echo "Monitoring trading activity... (Ctrl+C to stop)"
echo ""

cd "$(dirname "$0")"

# Function to format JSON nicely
format_trade() {
    python3 -c "
import sys, json
for line in sys.stdin:
    try:
        data = json.loads(line)
        print(f\"\\n{'='*80}\")
        print(f\"🎯 TRADE: {data.get('side')} on {data.get('ticker')}\")
        print(f\"{'='*80}\")
        print(f\"  Time:       {data.get('timestamp', 'N/A')[:19]}\")
        print(f\"  Size:       \${data.get('size', 0):.2f}\")
        print(f\"  Entry:      {data.get('entry_price', 0):.3f}\")
        print(f\"  P(True):    {data.get('p_true', 0):.1%}\")
        print(f\"  Edge:       {data.get('edge', 0):.1%}\")
        print(f\"  Status:     {data.get('status', 'unknown')}\")
        if data.get('pnl'):
            print(f\"  P&L:        \${data.get('pnl', 0):+.2f}\")
    except:
        pass
"
}

# Function to show balance
show_balance() {
    if [ -f data/trading/performance.json ]; then
        python3 -c "
import json
with open('data/trading/performance.json') as f:
    data = json.load(f)
    balance = data.get('balance', 0)
    peak = data.get('peak_balance', 200)
    pnl = balance - 200
    roi = (pnl / 200) * 100
    print(f\"💰 Balance: \${balance:.2f} | P&L: \${pnl:+.2f} ({roi:+.1f}%) | Peak: \${peak:.2f}\")
"
    fi
}

# Initial state
echo "📊 Current Status:"
show_balance
echo ""
echo "Recent trades:"
tail -3 data/trading/trades.jsonl 2>/dev/null | format_trade

echo ""
echo "────────────────────────────────────────────────────────────────────────────────"
echo "Watching for new activity..."
echo "────────────────────────────────────────────────────────────────────────────────"
echo ""

# Monitor for changes
tail -f data/trading/trades.jsonl 2>/dev/null | while read line; do
    echo "$line" | format_trade
    echo ""
    show_balance
    echo ""
    echo "────────────────────────────────────────────────────────────────────────────────"
done

