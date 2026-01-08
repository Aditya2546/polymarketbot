# Getting Started in 5 Minutes

## Step 1: Setup (2 minutes)

Open terminal and run:

```bash
cd polymarketbot
bash setup.sh
```

This will:
- Create Python virtual environment
- Install all dependencies
- Run tests to verify installation
- Create config file from template

## Step 2: Configure (1 minute)

Edit `config.yaml`:

```yaml
kalshi:
  api_key_id: "YOUR_KALSHI_API_KEY_ID"              # ← Add your API key ID
  private_key_path: "path/to/your/private_key.pem"  # ← Path to your RSA private key
```

**Get Kalshi API credentials** (RSA key-based authentication):
1. Sign up at https://kalshi.com
2. Go to Account → API Settings: https://kalshi.com/account/api
3. Generate API key pair (this gives you a key ID and downloads RSA private key)
4. Save the private key file (e.g., `kalshi_private_key.pem`) in a secure location
5. Copy the key ID and private key path into config.yaml

**Important**: Keep your private key file secure and never commit it to git!

## Step 3: Run (30 seconds)

```bash
source venv/bin/activate
python main.py --mode live
```

You should see a live dashboard like this:

```
┌────────────────────────────────────────────────────────────┐
│  Kalshi 15-Minute BTC Direction Assistant                  │
│  2026-01-07 12:34:56                                       │
├─────────────────────┬──────────────────┬───────────────────┤
│   📊 Market Info    │  ⚡ Edge Detection│  🎯 Trade Signal  │
│                     │                   │                   │
│ Market: BTCUP-...   │ Edge YES: +0.0423 │ [Signal appears   │
│ Baseline: $50,000   │ Edge NO:  -0.0127 │  when edge is     │
│ Time: 8m 23s        │ Latency: 87ms     │  detected]        │
│ YES: 0.45 / 0.47    │ Threshold: 0.030  │                   │
│ Spread: 4.4%        │ Has Signal: YES   │                   │
└─────────────────────┴──────────────────┴───────────────────┘
```

## What's Happening?

The system is:

1. **Monitoring** the active Kalshi 15-minute BTC market
2. **Computing** settlement-aligned probability using Monte Carlo
3. **Detecting** when market odds lag true probability
4. **Alerting** you when profitable opportunities appear

## When You See a Signal

You'll get:

- **Desktop notification** with trade details
- **Console highlight** showing recommended side and size
- **Alert sound** (if enabled)

Example signal:
```
🔔 Trade Signal: YES BTCUP-07JAN-15M

Side: YES
Edge: +4.23%
Size: $7.50
Reason: Delay capture - market lagging by 4.2%
```

**What to do**:
1. Review the signal details
2. Check Kalshi market manually
3. If you agree, place the trade manually
4. System continues monitoring

## Next Steps

### Try Paper Trading

Want the system to execute automatically (on paper)?

```bash
python main.py --mode paper
```

This simulates real trading without using money. Perfect for:
- Validating the strategy
- Learning how it works
- Tracking performance

### Review Performance

After running for a while, check your logs:

```bash
# View signals generated
cat logs/signals.json | jq

# View paper trades (if paper mode)
cat logs/trades.json | jq

# Check latency stats
cat logs/latency.json | jq
```

### Understand the Model

Read the docs:
- `README.md`: Full overview
- `USAGE_GUIDE.md`: Detailed instructions
- `QUICK_REFERENCE.md`: Cheat sheet

## Common First-Time Issues

### "Cannot connect to Kalshi"

**Solution**: Double-check your API credentials in `config.yaml`. Make sure there are no extra spaces.

### "No markets found"

**Solution**: Kalshi might not have an active 15m BTC market right now. Check kalshi.com to see if the market exists. These markets may only be active during certain hours.

### "Settlement index unavailable"

**Solution**: The system is trying to fetch BTC prices. This is normal on first run - it needs ~60 seconds of data before it can compute averages. Wait a minute and it should start working.

### Nothing happening

**Solution**: Make sure:
1. Virtual environment is activated: `source venv/bin/activate`
2. Config file exists: `ls config.yaml`
3. Internet connection is working
4. Kalshi market is open

## Tips for New Users

### Start Small
- Just watch signals for a day or two
- Don't trade immediately
- Learn what makes a good signal

### Understand Edge
- Edge = how much the market is mispriced
- Need >3% edge after costs to signal
- Higher edge = better opportunity

### Monitor Latency
- Latency = delay between price move and market update
- Low latency (<100ms) is good
- High latency (>200ms) hurts edge

### Respect Risk Limits
- Default: $8 max per trade
- Default: $20 max loss per day
- These are there to protect you

### Check Calibration
- System predicts probabilities (P(YES))
- Should be well-calibrated (accurate)
- Check Brier score in backtest (<0.20 is good)

## What NOT to Do

### ❌ Don't enable live trading immediately
Wait until you've:
- Backtested (>100 trades, positive Sharpe)
- Paper traded (>50 trades, profitable)
- Fully understand the system

### ❌ Don't ignore risk limits
If circuit breaker trips, there's a reason. Don't immediately resume without understanding what happened.

### ❌ Don't trade every signal blindly
Use your judgment. The system is a tool, not a replacement for thinking.

### ❌ Don't increase bankroll without validation
Start with $200 (or even less). Only scale up after proving profitability.

### ❌ Don't ignore latency
If latency is consistently high (>200ms), edge disappears quickly. Fix your network or don't trade.

## Getting Help

### Read First
1. This file (you're reading it!)
2. `QUICK_REFERENCE.md` - one-page cheat sheet
3. `USAGE_GUIDE.md` - detailed guide
4. `README.md` - project overview

### Check Logs
Most issues are explained in logs:
```bash
tail -f logs/main.log
```

### Common Errors

**"Config file not found"**
→ Run `cp config.template.yaml config.yaml`

**"Module not found"**
→ Run `pip install -r requirements.txt`

**"Permission denied: setup.sh"**
→ Run `chmod +x setup.sh`

**"Cannot import src"**
→ Make sure you're in the project root directory

## Success Checklist

After 5 minutes, you should have:

- [x] Environment set up
- [x] Config file created with API credentials
- [x] System running and showing live dashboard
- [x] Understanding of what the system does
- [x] First signal seen (if market is active)

## What's Next?

### Option A: Watch & Learn (Recommended)
Run in live mode for a few days. Watch signals. Learn patterns. Don't trade yet.

### Option B: Paper Trade
Enable paper trading to simulate execution. Track performance. Validate strategy.

### Option C: Backtest
Get historical BTC price data and run backtests. Optimize parameters. Understand edge.

### Option D: Deep Dive
Read all documentation. Understand the algorithms. Review code. Customize.

## Remember

- **This is a tool, not a magic money printer**
- **Edge exists but is small and fragile**
- **Risk management is critical**
- **Start small, validate, then scale**
- **Past performance ≠ future results**

## Quick Commands

```bash
# Live signals
python main.py --mode live

# Paper trading
python main.py --mode paper

# Backtest
python main.py --mode backtest --start 2024-01-01 --end 2024-12-31

# Run tests
pytest tests/ -v

# Check logs
tail -f logs/main.log

# View signals
cat logs/signals.json | jq

# Stop system
Ctrl+C
```

## Support

For software issues:
1. Check logs
2. Read documentation
3. Review error message
4. Check common issues above

For Kalshi account/API issues:
- Email: support@kalshi.com
- Website: https://kalshi.com

---

**You're ready to go! Good luck, trade safe, and remember: this is educational software. Use at your own risk.**

