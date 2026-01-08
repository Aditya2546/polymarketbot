# Quick Reference Card

## Installation

```bash
bash setup.sh
source venv/bin/activate
```

## Configuration

Edit `config.yaml`:
- Add Kalshi API key and secret
- Adjust risk parameters if needed
- Set alert preferences

## Commands

### Live Signals (Manual Trading)
```bash
python main.py --mode live
```

### Paper Trading (Automated Simulation)
```bash
python main.py --mode paper
```

### Backtesting
```bash
python main.py --mode backtest --start 2024-01-01 --end 2024-12-31
```

### Parameter Sweep
```bash
python main.py --mode sweep --param edge_threshold --range 0.01,0.05,0.01
```

## Key Metrics

| Metric | Good | Warning | Bad |
|--------|------|---------|-----|
| Win Rate | >58% | 52-58% | <52% |
| Sharpe Ratio | >2.0 | 1.5-2.0 | <1.5 |
| Brier Score | <0.15 | 0.15-0.20 | >0.20 |
| Latency | <100ms | 100-200ms | >200ms |
| Spread | <3% | 3-5% | >5% |

## Signal Types

1. **Delay Capture**: Market lagging true probability (primary)
2. **Momentum**: Strong directional move with continuation (secondary)
3. **Baseline Gap**: Interval starts away from baseline (secondary)

## Risk Defaults ($200 Bankroll)

- Max per trade: $8 (4%)
- Max exposure: $24 (12%)
- Daily loss limit: $20 (10%)
- Consecutive losses: 4 (then cooldown)
- Max drawdown: 25%

## No-Trade Conditions

- Neutral zone: P(YES) 45-55%
- Wide spread: >5%
- Final window: <15 seconds to settle
- Insufficient edge: <3% net
- Risk limits: Circuit breaker tripped

## Edge Calculation

```
Edge = P(true) - P(market) - (fees + slippage + latency)
```

Need edge >3% (default) to signal.

## File Structure

```
polymarketbot/
├── config.yaml          # Your configuration
├── main.py              # Entry point
├── src/
│   ├── data/           # Data sources
│   ├── models/         # Probability & settlement
│   ├── strategy/       # Signals & risk
│   ├── execution/      # Paper/live trading
│   └── ui/             # Console & alerts
├── logs/               # All logs
├── tests/              # Test suite
└── docs/               # Documentation
```

## Important Logs

- `logs/main.log`: System logs
- `logs/trades.json`: All trades/signals
- `logs/latency.json`: Latency tracking

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Can't connect | Check API credentials, internet |
| No markets | Verify Kalshi has active 15m BTC market |
| High latency | Check network, close other apps |
| Alerts not working | Check permissions/config |
| Poor performance | Review logs, check calibration |

## Safety Checklist

Before live trading:
- [ ] >100 backtest trades with positive Sharpe
- [ ] >50 paper trades with expected performance
- [ ] Understand all parameters
- [ ] Comfortable with potential losses
- [ ] Have reviewed all documentation
- [ ] Know how to emergency stop (Ctrl+C)

## Emergency Stop

**Keyboard**: `Ctrl+C` (stops system immediately)

**Manual Halt**:
```python
risk_manager.halt("Manual stop")
```

**Config Disable**:
```yaml
live_trading:
  enabled: false
```

## Support Checklist

When asking for help, provide:
1. Command you ran
2. Error message
3. Relevant log excerpts
4. Config (redact credentials!)
5. System info (OS, Python version)

## Key Equations

**Avg60 (Convention A)**:
```
avg60 = mean(prices[T-60:T-1])
```

**Settlement Outcome**:
```
outcome = "YES" if avg60 > baseline else "NO"
```

**P(YES) (Monte Carlo)**:
```
P(YES) = mean(simulated_avg60s > baseline)
```

**Position Size**:
```
size = min(max_risk, available) * edge_fraction
```

## Links

- **README**: Full overview
- **USAGE_GUIDE**: Detailed usage instructions
- **ARCHITECTURE**: Technical deep dive
- **Config Template**: `config.template.yaml`

## Contact

For Kalshi support: support@kalshi.com
For software issues: Review logs and documentation

---

**Remember**: This is a high-risk trading system. Only use with money you can afford to lose. Past performance does not guarantee future results.

