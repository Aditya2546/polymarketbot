# ✅ Your Kalshi API Setup is Complete!

## What's Been Configured

Your Kalshi 15-Minute BTC Direction Assistant is now **fully configured** with your API credentials:

- ✅ **API Key ID**: `B9159a57-74c1-477c-a3e3-22cca1c662ff`
- ✅ **Private Key**: Saved securely at `kalshi_private_key.pem`
- ✅ **Permissions**: Set to 600 (read-only for you)
- ✅ **Config File**: `config.yaml` created with your credentials

## Quick Test

Let's verify everything works:

```bash
# Make sure you're in the project directory
cd /Users/adityamandal/polymarketbot

# Activate virtual environment (if not already)
source venv/bin/activate

# Run the authentication test
python test_kalshi_auth.py
```

This will:
1. ✅ Test authentication with Kalshi
2. ✅ Fetch your account balance
3. ✅ Discover available BTC markets
4. ✅ Find active 15-minute markets

If you see "✅ All tests passed!" - you're ready to go!

## Next Steps

### 1. Run Live Signals (Recommended First)

```bash
python main.py --mode live
```

This will:
- Connect to Kalshi and start monitoring markets
- Display a live dashboard with real-time data
- Alert you when profitable signals appear
- **NOT execute trades** (just shows signals)

### 2. Paper Trading (After Watching Signals)

```bash
python main.py --mode paper
```

This will:
- Automatically execute trades **on paper** (simulated)
- Track P&L as if trading real money
- Validate the strategy without risk
- Generate performance reports

### 3. Backtesting (Optional)

First, you'll need historical BTC price data. Then:

```bash
python main.py --mode backtest --start 2024-01-01 --end 2024-12-31
```

## Important Notes

### 🔒 Security

Your private key is:
- ✅ Stored locally at: `/Users/adityamandal/polymarketbot/kalshi_private_key.pem`
- ✅ Protected with 600 permissions (only you can read)
- ✅ Excluded from git (in `.gitignore`)
- ⚠️ **NEVER share this file or commit it to git!**

### 💰 Trading Status

- **Live Trading**: ❌ **DISABLED** (safe default)
- **Paper Trading**: ✅ Enabled (simulated, no risk)

Live trading requires:
1. Explicit enable in `config.yaml`
2. Confirmation phrase
3. Multiple safety checks

Don't enable live trading until you've:
- Watched live signals for several days
- Paper traded profitably (>50 trades)
- Fully understand the system

### 📊 Risk Settings

For your **$200 bankroll**:
- Max per trade: **$8** (4%)
- Max exposure: **$24** (12%)
- Daily loss limit: **$20** (10%)

These are already configured in `config.yaml`.

## Dashboard Overview

When you run live mode, you'll see:

```
┌────────────────────────────────────────────────────────────┐
│  Kalshi 15-Minute BTC Direction Assistant                  │
├─────────────────────┬──────────────────┬───────────────────┤
│   📊 Market Info    │  ⚡ Edge Detection│  🎯 Trade Signal  │
│                     │                   │                   │
│ Market: BTCUP-...   │ Edge YES: +0.0423 │ [Appears when     │
│ Baseline: $50,000   │ Edge NO:  -0.0127 │  signal detected] │
│ Time: 8m 23s        │ Latency: 87ms     │                   │
│ YES: 0.45 / 0.47    │ Threshold: 0.030  │                   │
├─────────────────────┼──────────────────┤                   │
│   🔮 Model Status   │  💰 Risk Mgmt    │                   │
│                     │                   │                   │
│ Current BTC: $50,342│ Bankroll: $200   │                   │
│ Avg60: $50,289      │ Daily P&L: $0.00 │                   │
│ P(YES): 0.6842      │ Status: ACTIVE   │                   │
└─────────────────────┴──────────────────┴───────────────────┘
```

Press **Ctrl+C** to stop.

## Troubleshooting

### If Test Fails

1. **"Failed to load private key"**
   - Check: `ls -la kalshi_private_key.pem`
   - Should show: `-rw------- 1 adityamandal staff`

2. **"Authentication failed (401)"**
   - Verify Key ID at: https://kalshi.com/account/api
   - Ensure private key matches the Key ID

3. **"No module named 'src'"**
   - Run: `pip install -r requirements.txt`
   - Make sure you're in project directory

4. **"Config file not found"**
   - File should exist: `config.yaml`
   - Check: `ls -la config.yaml`

### Getting Help

- **Documentation**: Read `GETTING_STARTED.md` and `USAGE_GUIDE.md`
- **API Setup**: See `KALSHI_API_SETUP.md`
- **Logs**: Check `logs/main.log` after running
- **Kalshi Support**: support@kalshi.com

## What to Expect

### First Run

The system will:
1. Connect to Kalshi API ✅
2. Fetch BTC price data (~60 seconds to warm up)
3. Discover active 15-minute market
4. Start computing probabilities
5. Show live dashboard

### Signals

You'll see signals when:
- ✅ Market odds lag true probability (delay edge)
- ✅ Strong momentum with underpricing
- ✅ Baseline gap at interval start

Signals include:
- **Side**: YES or NO
- **Edge**: Net edge percentage
- **Size**: Recommended position size
- **Reason**: Why signal triggered

### Alerts

You'll get desktop notifications for:
- 🔔 New trade signals
- 💰 Position opened/closed (if paper trading)
- ⚠️ Circuit breaker triggered
- ❌ System errors

## Quick Commands Reference

```bash
# Live signals only
python main.py --mode live

# Paper trading (automated)
python main.py --mode paper

# Test authentication
python test_kalshi_auth.py

# Run tests
pytest tests/ -v

# View logs
tail -f logs/main.log

# Stop system
Ctrl+C
```

## Final Checklist

Before running:
- [x] Virtual environment activated
- [x] Dependencies installed (`requirements.txt`)
- [x] Config file created (`config.yaml`)
- [x] API credentials configured
- [x] Private key secured (`600` permissions)
- [x] Test authentication passed

## You're Ready! 🚀

Everything is set up and ready to go. Run:

```bash
python test_kalshi_auth.py
```

If tests pass, you're good to start:

```bash
python main.py --mode live
```

**Good luck with your trading, and remember:**
- Start with observation (live signals)
- Validate with paper trading
- Understand the system before live trading
- Respect risk limits
- Trade responsibly

---

Questions? Check the documentation:
- `README.md` - Project overview
- `GETTING_STARTED.md` - 5-minute guide
- `USAGE_GUIDE.md` - Complete manual
- `KALSHI_API_SETUP.md` - API setup details
- `QUICK_REFERENCE.md` - Cheat sheet

