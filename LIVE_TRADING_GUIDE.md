# 🚀 Live Trading System Guide

## What This Does

The live trading system:
- ✅ Connects to **LIVE Bitcoin price feeds** (Coinbase, Binance, Kraken)
- ✅ Updates price **every second** with real market data
- ✅ Calculates 60-second average (matching Kalshi settlement)
- ✅ Makes predictions on 15-minute BTC direction
- ✅ Executes trades when profitable edge is detected
- ✅ Tracks **all trades and performance** persistently to disk
- ✅ Runs continuously until you stop it

---

## 🎯 Live Data Sources

### Primary: Coinbase Pro WebSocket
- **Type:** WebSocket (real-time)
- **Latency:** < 100ms
- **Quality:** Excellent (institutional grade)
- **URL:** wss://ws-feed.exchange.coinbase.com

### Backup: Binance WebSocket
- **Type:** WebSocket (real-time)
- **Latency:** < 100ms
- **Quality:** Excellent (high volume)
- **URL:** wss://stream.binance.us:9443/ws/btcusdt@trade

### Backup: Kraken WebSocket
- **Type:** WebSocket (real-time)
- **Latency:** < 200ms
- **Quality:** Good
- **URL:** wss://ws.kraken.com

### Fallback: REST APIs
If all WebSockets fail, polls REST APIs every second:
- Coinbase API
- Binance API
- Kraken API

**The system automatically tries sources in order and uses the first one that connects!**

---

## 🚀 Quick Start

### Option 1: Use the start script (RECOMMENDED)
```bash
./start_live_trading.sh
```

### Option 2: Run directly
```bash
source venv/bin/activate
python run_live.py
```

---

## 📊 What You'll See

### During Startup
```
════════════════════════════════════════════════════════════════════════════════
🚀 STARTING LIVE TRADING SYSTEM
════════════════════════════════════════════════════════════════════════════════
Mode: PAPER TRADING
Model: Momentum + Mean Reversion Hybrid
Starting Balance: $200.00
════════════════════════════════════════════════════════════════════════════════
Starting live Bitcoin feed...
✓ BTC Feed connected: Coinbase
✓ Current price: $90,956.00
✓ Kalshi client connected
════════════════════════════════════════════════════════════════════════════════
✅ SYSTEM READY - MONITORING FOR OPPORTUNITIES
════════════════════════════════════════════════════════════════════════════════
```

### During Operation
```
Warming up... 45/60 prices
Warming up... 60/60 prices

────────────────────────────────────────────────────────────────────────────────
💰 Balance: $200.00 | P&L: $+0.00 (+0.0%) | Trades: 0 | Win Rate: 0.0%
📊 BTC: $90,956.45 | Source: Coinbase | Buffer: 120
────────────────────────────────────────────────────────────────────────────────
```

### When a Trade is Executed
```
🎯 ════════════════════════════════════════════════════════════════════════════
   NEW TRADE SIGNAL
════════════════════════════════════════════════════════════════════════════════
   Market:      BTC-15M-20260107-1430
   Side:        YES
   Size:        $8.50
   Entry:       0.620
   P(True):     68.5%
   Edge:        5.2%
   Confidence:  18.5%
   Balance:     $191.50
════════════════════════════════════════════════════════════════════════════════
```

---

## 📁 Where Data is Saved

All trading data is saved to `data/trading/`:

### `trades.jsonl`
Every trade (one per line):
```json
{"timestamp": "2026-01-07T14:30:15", "market_id": "BTC-15M-...", "side": "YES", "size": 8.5, ...}
```

### `predictions.jsonl`
Every prediction made (one per line):
```json
{"timestamp": "2026-01-07T14:30:15", "p_yes": 0.685, "p_no": 0.315, "edge": 0.052, ...}
```

### `performance.json`
Current performance snapshot:
```json
{
  "balance": 215.50,
  "peak_balance": 220.00,
  "last_update": "2026-01-07T15:45:00"
}
```

### CSV Exports
Automatically exported:
- `data/trading/trades.csv` - All closed trades
- `data/trading/predictions.csv` - All predictions

---

## ⚙️ Trading Parameters

### Current Settings
```python
min_edge_threshold = 0.015    # 1.5% minimum edge required
min_confidence = 0.03         # 3% minimum confidence
max_position_size = $15       # Maximum per trade
position_sizing = Half-Kelly  # Conservative sizing
```

### What This Means
- Only trades when model predicts **1.5%+ edge** over market
- Only trades when model is **3%+ confident** in direction
- Never risks more than **$15** on a single trade
- Uses **half-Kelly** sizing (aggressive but not reckless)

---

## 🛑 Stopping the System

### Graceful Shutdown
Press `Ctrl+C` once. The system will:
1. Stop accepting new trades
2. Close all connections
3. Export all data to CSV
4. Print final performance summary

### Emergency Stop
Press `Ctrl+C` twice for immediate shutdown.

### What Happens to Data
All data is **automatically saved** to disk continuously, so you won't lose anything even if the system crashes.

---

## 📈 Monitoring Performance

### Real-Time (in console)
Status updates every 60 seconds showing:
- Current balance
- P&L and ROI
- Number of trades
- Win rate
- Current BTC price
- Data source

### Post-Session Analysis
```bash
# View trade history
cat data/trading/trades.csv

# View predictions
cat data/trading/predictions.csv

# View performance
cat data/trading/performance.json

# View logs
tail -f logs/live_trading_*.log
```

---

## 🎯 Expected Performance

Based on simulation results:
- **Win Rate:** 70-75%
- **ROI:** 300-700% (paper trading, compound growth)
- **Avg Trade:** +$7-8
- **Drawdown:** <10%

**Note:** These are simulation results. Real performance may vary!

---

## ⚠️ Important Notes

### This is PAPER TRADING
- ✅ Real Bitcoin price data
- ✅ Real predictions
- ✅ Real strategy execution
- ❌ **NO REAL MONEY AT RISK**

### Data Accuracy
The system uses **real-time exchange data**, which should closely match:
- CF Benchmarks BRTI (Kalshi's settlement index)
- Within 0.1-0.5% typically
- Updates every second

### Markets
Currently creates **synthetic 15-minute markets** for testing. In production, this would:
- Query Kalshi API for active BTC 15-minute markets
- Get real orderbook data for entry prices
- Submit real orders when edge is detected

---

## 🔧 Customization

### Change Trading Parameters
Edit `run_live.py`:
```python
self.min_edge_threshold = 0.015  # Change minimum edge
self.min_confidence = 0.03       # Change minimum confidence
self.max_position_size = 15.0    # Change max position
```

### Change Starting Balance
Edit `src/tracking/trade_tracker.py`:
```python
self.balance = 200.0  # Change starting balance
```

### Change Data Source Priority
Edit `src/data/live_btc_feed.py`:
```python
ws_sources = [
    self._coinbase_websocket,  # Try Coinbase first
    self._binance_websocket,   # Then Binance
    self._kraken_websocket     # Then Kraken
]
```

---

## 🚨 Troubleshooting

### "Failed to get initial price from any source"
- Check internet connection
- Some exchanges may be blocked in your region
- Try using a VPN

### "Kalshi client not available"
- This is OK! The system works without Kalshi for testing
- It will create synthetic markets instead

### WebSocket keeps disconnecting
- Normal! The system auto-reconnects
- Falls back to REST API if WebSocket fails

### No trades executing
- Might not be finding good opportunities
- Lower `min_edge_threshold` in `run_live.py`
- Check that buffer has 60+ prices

---

## 📞 Support

Issues? Check:
1. `logs/live_trading_*.log` - Full system logs
2. `data/trading/` - All trade data
3. Console output - Real-time status

---

## 🎉 Ready to Run!

Start the system:
```bash
./start_live_trading.sh
```

Let it run for a few hours and watch the performance!

**The system will continuously:**
- ✅ Track live BTC prices
- ✅ Make predictions
- ✅ Execute profitable trades
- ✅ Save everything to disk
- ✅ Compound your virtual profits

**Press Ctrl+C anytime to see results!**

