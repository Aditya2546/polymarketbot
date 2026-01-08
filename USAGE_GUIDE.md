# Usage Guide

## Quick Start

### 1. Installation

```bash
# Clone repository
cd polymarketbot

# Run setup script
bash setup.sh

# This will:
# - Create virtual environment
# - Install dependencies
# - Create config from template
# - Run tests
```

### 2. Configuration

Edit `config.yaml` with your credentials:

```yaml
kalshi:
  api_key: "your_kalshi_api_key"
  api_secret: "your_kalshi_api_secret"
```

**Important**: Kalshi API credentials are required. Sign up at https://kalshi.com

### 3. First Run

```bash
# Activate virtual environment
source venv/bin/activate

# Run live signals
python main.py --mode live
```

You should see a live console dashboard updating in real-time.

## Modes of Operation

### Live Signal Generation

Monitor markets and generate manual trade signals:

```bash
python main.py --mode live
```

**Features**:
- Real-time market monitoring
- Settlement-aligned probability computation
- Edge detection and signal generation
- Live console dashboard
- Desktop/Telegram alerts when opportunities appear

**Use case**: You execute trades manually based on signals.

### Paper Trading

Automatically execute trades on paper to validate strategy:

```bash
python main.py --mode paper
```

**Features**:
- All live signal features
- Automated signal execution (simulated)
- Realistic fill modeling (delays, slippage, misses)
- P&L tracking
- Performance metrics

**Use case**: Validate strategy with simulated execution before going live.

### Backtesting

Test strategy on historical data:

```bash
python main.py --mode backtest --start 2024-01-01 --end 2024-12-31
```

**Features**:
- Historical simulation over date range
- Settlement rule accuracy
- Performance metrics (Sharpe, win rate, drawdown)
- Brier score for calibration
- Edge attribution by signal type

**Use case**: Optimize parameters and validate strategy before live deployment.

### Parameter Sweep

Optimize strategy parameters:

```bash
python main.py --mode sweep --param edge_threshold --range 0.01,0.05,0.01
```

**Features**:
- Automated parameter testing
- Multiple configurations tested
- Best parameters identified
- Results exported

**Use case**: Find optimal edge thresholds, time windows, etc.

## Understanding the Dashboard

### Live Console Layout

```
┌────────────────────────────────────────────────────────────┐
│  Kalshi 15-Minute BTC Direction Assistant                  │
│  2026-01-07 12:34:56                                       │
├─────────────────────┬──────────────────┬───────────────────┤
│   📊 Market Info    │  ⚡ Edge Detection│  🎯 Trade Signal  │
│                     │                   │                   │
│ Market: BTCUP-...   │ Edge YES: +0.0423 │ YES BTCUP-...     │
│ Baseline: $50,000   │ Edge NO:  -0.0127 │                   │
│ Time: 8m 23s        │ Latency: 87ms     │ Type: delay_cap.. │
│ YES: 0.45 / 0.47    │ Threshold: 0.030  │ Edge: +4.23%      │
│ Spread: 4.4%        │ Has Signal: YES   │ Size: $7.50       │
│                     │                   │                   │
├─────────────────────┼──────────────────┼───────────────────┤
│   🔮 Model Status   │  💰 Risk Mgmt    │                   │
│                     │                   │                   │
│ Current BTC: $50,342│ Bankroll: $203.45│                   │
│ Avg60 (A): $50,289  │ Daily P&L: +$3.45│                   │
│ Distance: +$289     │ Drawdown: 1.2%   │                   │
│ P(YES): 0.6842      │ Open: 1 position │                   │
│ Volatility: 0.00041 │ Available: $16   │                   │
│                     │ STATUS: ACTIVE   │                   │
└─────────────────────┴──────────────────┴───────────────────┘
```

### Key Metrics Explained

**Market Info**:
- **Baseline**: Starting BTC price for the interval (from CF Benchmarks)
- **Time to Settle**: Countdown until settlement
- **YES/NO**: Current bid/ask prices on Kalshi
- **Spread**: Bid-ask spread as percentage

**Model Status**:
- **Current BTC**: Latest BTC price from feed
- **Avg60**: 60-second rolling average (settlement value)
- **Distance**: How far avg60 is from baseline (positive = above)
- **P(YES)**: Probability that final avg60 > baseline
- **Volatility**: Estimated 1-second return volatility

**Edge Detection**:
- **Edge YES/NO**: Net edge after costs for each side
- **Latency**: Measured lag between underlying and market updates
- **Threshold**: Minimum edge required (adjusted for latency)
- **Has Signal**: Whether edge exceeds threshold

**Trade Signal** (when active):
- **Side**: YES or NO
- **Type**: delay_capture, momentum, or baseline_gap
- **Edge**: Net edge percentage
- **Size**: Recommended position size (from risk manager)
- **Reason**: Why signal triggered

**Risk Management**:
- **Bankroll**: Current capital
- **Daily P&L**: Profit/loss since start of day
- **Drawdown**: Decline from peak bankroll
- **Open Positions**: Number of active trades
- **Available**: Risk budget for new trades
- **STATUS**: ACTIVE, HALTED, or COOLDOWN

## Interpreting Signals

### Signal Types

#### 1. Delay Capture (Primary)

**What it is**: Market odds haven't updated to reflect rapid price movement.

**Example**:
```
BTC jumps from $50,000 to $50,500 in 30 seconds
→ Avg60 updates immediately
→ P(YES) jumps from 0.50 to 0.75
→ But Kalshi market still shows YES at 0.48
→ Edge = 0.75 - 0.48 - costs = +0.24 (24%!)
→ SIGNAL: BUY YES
```

**Why it works**: Kalshi market makers may be slower to react than our settlement-aligned model.

#### 2. Momentum Confirmation (Secondary)

**What it is**: Strong directional movement early in interval with market underpricing continuation.

**Example**:
```
Interval starts, BTC immediately moves +0.5% above baseline
→ 12 minutes remaining
→ Model estimates high probability of staying above
→ But market still near 50-50
→ SIGNAL: BUY YES
```

**Why it works**: Early strong moves often persist due to trend/momentum.

#### 3. Baseline Gap at Open (Secondary)

**What it is**: New interval starts with price already away from baseline.

**Example**:
```
New 15m interval begins
→ Baseline set at $50,000
→ But current price is already $50,200
→ Market hasn't fully priced in the gap
→ SIGNAL: BUY YES (quick)
```

**Why it works**: Market may take a few seconds to price in the starting gap.

### When NOT to Trade

The system will NOT generate signals when:

1. **Neutral Zone**: P(YES) between 45-55% (unclear outcome)
2. **Wide Spread**: Spread > 5% (too much slippage)
3. **Final Window**: < 15 seconds to settle (unless huge edge)
4. **Insufficient Edge**: Net edge below threshold (after costs)
5. **Risk Limits**: Circuit breakers or exposure limits hit

## Risk Management

### Default Settings ($200 Bankroll)

```yaml
max_risk_per_trade: $8 (4% of bankroll)
max_open_exposure: $24 (12% of bankroll)
daily_loss_limit: $20 (10% of bankroll)
consecutive_loss_limit: 4 trades
max_drawdown: 25% from peak
```

### Circuit Breakers

**Daily Loss Limit**: Trading halts if you lose more than $20 in a day.

**Consecutive Losses**: After 4 losing trades in a row, enters 30-minute cooldown.

**Max Drawdown**: Trading halts if bankroll drops 25% from peak.

**Manual Override**: You can resume trading with `risk_manager.resume()` in code, but use caution!

### Position Sizing

Size scales with edge:

```
Edge 2% → Minimum size (25% of max)
Edge 3% → ~50% of max
Edge 5%+ → Full size (100% of max)
```

This Kelly-inspired approach allocates more capital to higher-edge opportunities.

## Alerts

### Desktop Notifications

Automatically shown on macOS/Linux/Windows when:
- New trade signal generated
- Position opened (paper/live)
- Position closed
- Circuit breaker triggered

### Telegram Bot

Set up in `config.yaml`:

```yaml
alerts:
  telegram:
    enabled: true
    bot_token: "YOUR_BOT_TOKEN"
    chat_id: "YOUR_CHAT_ID"
```

Get bot token from [@BotFather](https://t.me/BotFather) on Telegram.

### Webhook

Send alerts to Discord, Slack, or custom endpoint:

```yaml
alerts:
  webhook:
    enabled: true
    url: "https://discord.com/api/webhooks/..."
```

## Advanced Configuration

### Settlement Convention

Choose between two avg60 definitions:

```yaml
settlement:
  convention: "A"  # [T-60, T-1] - excludes settle moment
  # OR
  convention: "B"  # (T-60, T] - includes settle moment
```

**Recommendation**: Use "A" until you validate Kalshi's exact rule. Set `log_both: true` to compare.

### Monte Carlo Simulations

More simulations = more accurate but slower:

```yaml
probability:
  monte_carlo:
    num_simulations: 10000  # Default
    # 5000 = faster but less accurate
    # 20000 = slower but more accurate
```

**Recommendation**: 10,000 is good balance for 1Hz updates.

### Edge Thresholds

Adjust minimum edge required:

```yaml
edge_detection:
  min_edge_threshold: 0.03  # 3% default
  # Higher = fewer but higher-quality signals
  # Lower = more signals but lower edge
```

**Recommendation**: Start with 3% and backtest other values.

### Data Source

Use direct CF Benchmarks if you have access:

```yaml
data_sources:
  brti:
    use_cf_benchmarks: true
    cf_api_key: "YOUR_CF_API_KEY"
```

Otherwise, uses free exchange composite (marked as approximate).

## Backtesting Deep Dive

### Preparing Historical Data

Your CSV should have two columns:

```csv
timestamp,price
1704067200,50123.45
1704067201,50124.12
1704067202,50125.89
...
```

- **timestamp**: Unix seconds or ISO 8601
- **price**: BTC price in USD

### Running Backtest

```bash
python main.py --mode backtest \
  --start 2024-01-01 \
  --end 2024-12-31
```

### Understanding Results

```
Backtest Results
================
Trades: 156
Win Rate: 58.3%
Total P&L: +$87.45
Avg P&L per Trade: +$0.56
Max Drawdown: 8.2%
Sharpe Ratio: 1.82
Brier Score: 0.183 (lower is better)

Edge Attribution:
  delay_capture: +$62.30 (71%)
  momentum: +$18.20 (21%)
  baseline_gap: +$6.95 (8%)

Worst Losing Streak: 6 trades
```

**Key Metrics**:
- **Win Rate**: Should be > 55% for profitable strategy
- **Sharpe Ratio**: > 1.5 is good, > 2.0 is excellent
- **Brier Score**: < 0.20 means well-calibrated probabilities
- **Edge Attribution**: Shows which signal types are most profitable

### Parameter Optimization

Test different thresholds:

```bash
# Test edge thresholds from 1% to 5%
python main.py --mode sweep \
  --param edge_threshold \
  --range 0.01,0.05,0.01
```

Results will show optimal value based on your chosen metric (Sharpe, P&L, etc.).

## Live Trading (Advanced)

### ⚠️ DANGER ZONE ⚠️

Live trading uses real money and can result in losses. Only enable after:

1. ✅ Extensive backtesting (>100 trades, positive Sharpe)
2. ✅ Paper trading validation (>50 trades, profitable)
3. ✅ Understanding all risk parameters
4. ✅ Comfortable with potential losses

### Enabling Live Trading

In `config.yaml`:

```yaml
live_trading:
  enabled: true
  confirmation_required: true
  confirmation_phrase: "I UNDERSTAND THE RISKS"
```

When you run the system, you'll need to type the confirmation phrase.

### Live Trading Safeguards

- **Disabled by default**: Must explicitly enable
- **Confirmation phrase**: Must type phrase to activate
- **All risk limits apply**: Circuit breakers active
- **Every trade logged**: Full audit trail
- **Emergency stop**: Ctrl+C or manual halt

### Monitoring Live Trading

Watch these metrics closely:

- **Latency**: Should be < 200ms consistently
- **Fill Rate**: Should be > 90%
- **Slippage**: Actual vs expected execution price
- **Win Rate**: Should match backtest ± 5%

If any metric diverges significantly from backtest expectations, HALT and investigate.

## Troubleshooting

### "Cannot connect to Kalshi WebSocket"

1. Check API credentials in config.yaml
2. Verify internet connection
3. Check Kalshi API status: https://status.kalshi.com
4. Ensure firewall allows WebSocket connections

### "Settlement index unavailable"

1. If using CF Benchmarks, verify API key
2. If using fallback, check exchange API availability
3. System will retry automatically
4. Check `logs/main.log` for details

### "No markets found"

1. Kalshi may not have active 15m BTC market at this time
2. Check Kalshi website for market availability
3. Markets may only be active during certain hours
4. Use `--market-id` flag to specify market manually

### "Alerts not working"

Desktop:
- macOS: Grant notification permissions in System Preferences
- Linux: Ensure notification daemon running
- Windows: Check Windows notification settings

Telegram:
- Verify bot token is correct
- Ensure chat_id is correct (use @userinfobot to get it)
- Bot must have been started by you (send /start to bot)

### High Latency

If latency > 200ms consistently:

1. Check internet connection speed
2. Close other bandwidth-heavy applications
3. Consider upgrading internet plan
4. System will auto-widen thresholds, but performance may suffer

### Circuit Breaker Triggered

If trading halted:

1. Review `logs/trades.json` to understand what happened
2. Analyze losing trades
3. Consider adjusting parameters
4. Don't immediately resume - understand root cause first

### Poor Performance

If losing money in paper trading:

1. Check calibration: Is Brier score < 0.20?
2. Review edge attribution: Which signals are losing?
3. Compare live latency to backtest assumptions
4. Verify spread assumptions match reality
5. Consider tightening edge threshold

## Best Practices

### 1. Start Small

Begin with paper trading and monitor for at least 50 trades before considering live trading.

### 2. Monitor Calibration

Your P(YES) predictions should be well-calibrated. Check Brier score regularly.

### 3. Track Latency

High latency kills edge. If latency spikes, signals may not be profitable.

### 4. Review Logs Daily

Check `logs/trades.json` daily to understand what's working and what isn't.

### 5. Backtest After Changes

Any config change should be backtested before going live.

### 6. Respect Circuit Breakers

If breakers trip, it's for a reason. Don't immediately resume without investigation.

### 7. Keep Bankroll Separate

Use a dedicated Kalshi account for this strategy. Don't mix with other trading.

### 8. Document Everything

Keep notes on parameter changes, performance, and observations.

### 9. Stay Updated

Monitor Kalshi for any changes to settlement rules or market structure.

### 10. Have an Exit Plan

Define conditions under which you'll stop using the strategy (e.g., 3 consecutive losing weeks).

## Getting Help

### Logs

All logs are in the `logs/` directory:
- `main.log`: System logs
- `trades.json`: Trade history
- `latency.json`: Latency measurements

### Debug Mode

Enable debug logging in `config.yaml`:

```yaml
logging:
  level: "DEBUG"
development:
  debug: true
  save_debug_data: true
```

### Support

For issues with the software, check:
1. This documentation
2. `ARCHITECTURE.md` for technical details
3. Code comments
4. Test files for examples

## Disclaimer

This software is for educational purposes. Trading involves substantial risk of loss. Past performance does not guarantee future results. You are responsible for your trading decisions and outcomes.

**IMPORTANT**: This is not financial advice. Do your own research. Only trade with money you can afford to lose.

