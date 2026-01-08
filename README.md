# Kalshi 15-Minute BTC Direction Assistant

A high-performance trading assistant for Kalshi's 15-minute BTC markets. Detects delay-based edge opportunities by computing settlement-aligned probabilities and comparing them to market odds.

## Features

- **Settlement-Aligned Model**: Uses CF Benchmarks BRTI proxy with 60-second averaging to match Kalshi's settlement rule
- **Delay Edge Detection**: Identifies when market odds lag true probability updates
- **Real-time Signals**: Live console UI with desktop/webhook alerts
- **Risk Management**: Aggressive but safe position sizing for $200 bankroll
- **Backtesting**: Full simulation engine with calibration metrics
- **Paper Trading**: Automated execution simulation for validation
- **Optional Polymarket Overlay**: Wallet flow and odds as secondary confirmation

## Quick Start (5 Minutes)

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Credentials

Copy the template and fill in your API keys:

```bash
cp config.template.yaml config.yaml
# Edit config.yaml with your Kalshi API key ID and private key path
# Get credentials at: https://kalshi.com/account/api
```

### 3. Run Live Signals

```bash
python main.py --mode live
```

This will:
- Connect to Kalshi WebSocket for market data
- Start computing settlement-aligned probabilities
- Display real-time signals in the console
- Send alerts when edge opportunities appear

## Modes

### Live Signal Generation
```bash
python main.py --mode live
```
Watch markets and generate manual trading signals with alerts.

### Paper Trading
```bash
python main.py --mode paper
```
Automatically execute trades on paper and track P&L.

### Backtesting
```bash
python main.py --mode backtest --start 2024-01-01 --end 2024-12-31
```
Run historical simulation with performance metrics.

### Parameter Sweep
```bash
python main.py --mode sweep --param edge_threshold --range 0.01,0.05,0.01
```
Optimize strategy parameters on historical data.

## Configuration

Edit `config.yaml` to customize:

- **Bankroll**: Default $200, adjust risk limits proportionally
- **Edge Thresholds**: Minimum edge required to signal (default: 0.03)
- **Risk Limits**: Per-trade, total exposure, daily loss limits
- **Settlement Convention**: Choose avg60_A (T-60 to T-1) or avg60_B (T-60 to T)
- **Latency Buffers**: Auto-adjusted based on measured lag
- **Signal Types**: Enable/disable delay capture, momentum, baseline-gap
- **Alerts**: Configure Telegram/webhook/desktop notifications

## Architecture

```
├── src/
│   ├── data/
│   │   ├── brti_feed.py          # Settlement-grade BTC index
│   │   ├── kalshi_client.py      # WebSocket + REST API
│   │   └── polymarket_overlay.py # Optional wallet flow
│   ├── models/
│   │   ├── settlement_engine.py  # avg60 computation
│   │   ├── probability_model.py  # Monte Carlo P(YES)
│   │   └── edge_detector.py      # Delay signal logic
│   ├── strategy/
│   │   ├── signal_generator.py   # Trade recommendations
│   │   └── risk_manager.py       # Position sizing
│   ├── execution/
│   │   ├── paper_trader.py       # Simulated execution
│   │   └── live_trader.py        # Real execution (disabled)
│   ├── backtest/
│   │   ├── engine.py             # Historical simulation
│   │   └── metrics.py            # Performance analysis
│   └── ui/
│       ├── console.py            # Live dashboard
│       └── alerts.py             # Multi-channel alerts
├── tests/                        # Unit and integration tests
├── data/                         # Historical data cache
├── logs/                         # Structured JSON logs
├── config.yaml                   # User configuration
└── main.py                       # Entry point
```

## Settlement Rule

Kalshi 15m BTC markets settle using:
1. **Baseline**: BTC price at interval start (from CF Benchmarks BRTI)
2. **Final Value**: 60-second simple average of BRTI immediately before settle time
3. **Outcome**: YES if final > baseline, NO otherwise

The bot models this EXACTLY using a ring buffer and rolling average.

## Signal Types

### 1. Delay Capture (Primary)
- Underlying price moves rapidly
- avg60 and p_true update immediately
- Kalshi market odds lag behind
- Edge = p_true - p_market exceeds threshold

### 2. Momentum Confirmation (Secondary)
- Strong directional movement early in interval
- Market underprices continuation probability
- Used when delay is less obvious but trend is clear

### 3. Baseline Gap at Open (Secondary)
- New interval starts with price already away from baseline
- Market hasn't fully priced in immediate bias
- Quick scalp opportunity

## Risk Management

For $200 bankroll (aggressive but safe):

- **Max Risk Per Trade**: $8 (4% of bankroll)
- **Max Open Exposure**: $24 (12% of bankroll)
- **Daily Loss Limit**: $20 (10% of bankroll)
- **Consecutive Loss Limit**: 4 trades, then cooldown
- **No-Trade Window**: Last 15 seconds before settlement (configurable)
- **Spread Gate**: No trade if spread > 5% (configurable)

Position sizing scales with edge:
```
size = min(max_risk, max_available) * min(1.0, edge / target_edge)
```

## Backtest Metrics

- **Win Rate**: % of profitable trades
- **Average Edge at Entry**: Mean edge when signal triggered
- **Profit Per Trade**: Mean P&L per trade
- **Max Drawdown**: Worst peak-to-trough loss
- **Sharpe Ratio**: Risk-adjusted returns
- **Brier Score**: Probability calibration quality
- **Edge Attribution**: P&L by signal type (delay vs momentum vs gap)

## Testing

```bash
# Run all tests
pytest tests/

# Test settlement engine
pytest tests/test_settlement_engine.py -v

# Test probability model
pytest tests/test_probability_model.py -v

# Test risk management
pytest tests/test_risk_manager.py -v
```

## Safety Features

- **Live Trading Disabled by Default**: Requires explicit config flag + confirmation
- **Multiple Circuit Breakers**: Daily loss, consecutive loss, exposure limits
- **Latency Monitoring**: Auto-widens thresholds when lag detected
- **Rate Limiting**: Respects API limits with exponential backoff
- **Secure Credentials**: Environment variables + gitignored secrets
- **Structured Logging**: All decisions logged with context for audit

## Data Sources

### Primary: Settlement-Grade BTC Index
- **Preferred**: Direct CF Benchmarks BRTI realtime feed (requires license)
- **Fallback**: High-quality composite from Coinbase, Bitstamp, Kraken (labeled as approximate)

### Kalshi Market Data
- **WebSocket**: Realtime orderbook and trades
- **REST API**: Market metadata, positions, balance

### Optional: Polymarket Overlay
- **Market Odds**: Current equivalent 15m BTC market price
- **Wallet Flow**: On-chain activity from high-performing wallets
  - Filtered by realized profitability (computed from data)
  - Used as secondary confirmation signal only

## Performance Expectations

- **Latency**: <100ms from underlying tick to signal (local)
- **Update Frequency**: 1Hz for probabilities, immediate for edge detection
- **Memory**: ~50MB for ring buffers and simulation
- **CPU**: ~10% single core (Monte Carlo optimized with NumPy)

## Troubleshooting

### "Cannot connect to Kalshi WebSocket"
- Check API credentials in config.yaml
- Verify network connectivity
- Check Kalshi API status

### "Settlement index unavailable"
- BRTI feed may require license/subscription
- System will fall back to exchange composite
- Warning logged when using fallback

### "No markets found"
- Kalshi may not have active 15m BTC market at this time
- Check market hours and availability
- Use `--market-id` flag to specify manual market

### "Alerts not working"
- Check alert configuration in config.yaml
- Verify Telegram bot token or webhook URL
- Desktop notifications require permissions on macOS

## License

MIT License - see LICENSE file

## Disclaimer

This software is for educational and informational purposes only. Trading cryptocurrencies involves substantial risk of loss. The authors are not responsible for any financial losses incurred from using this software. Always do your own research and trade at your own risk.

**IMPORTANT**: Live trading is DISABLED by default. Paper trading mode is recommended for validation before any real capital deployment.

