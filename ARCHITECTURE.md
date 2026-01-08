# Architecture Overview

## System Design

The Kalshi 15-Minute BTC Direction Assistant is designed as a modular, high-performance trading system with the following key principles:

1. **Settlement-Aligned**: All models and calculations are aligned to Kalshi's exact settlement rule using CF Benchmarks BRTI 60-second average
2. **Low Latency**: Optimized data structures (ring buffers) and algorithms (NumPy/Numba) for sub-100ms response times
3. **Safety First**: Multiple layers of risk management and circuit breakers to protect capital
4. **Observable**: Comprehensive logging, metrics, and live UI for full transparency

## Component Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Main Entry Point                         │
│                      (main.py)                               │
└────────────────────┬────────────────────────────────────────┘
                     │
         ┌───────────┴───────────┐
         │                       │
    ┌────▼────┐            ┌────▼────┐
    │ Config  │            │ Logging │
    └────┬────┘            └────┬────┘
         │                       │
         └───────────┬───────────┘
                     │
         ┌───────────▼───────────┐
         │   Trading System      │
         │   Orchestrator        │
         └───────────┬───────────┘
                     │
     ┌───────────────┼───────────────┐
     │               │               │
┌────▼────┐    ┌────▼────┐    ┌────▼────┐
│  Data   │    │ Models  │    │Strategy │
│ Sources │    │         │    │         │
└─────────┘    └─────────┘    └─────────┘
     │               │               │
     │         ┌─────┴─────┐         │
     │    ┌────▼────┐ ┌────▼────┐   │
     │    │Settlement│ │Probability│ │
     │    │ Engine  │ │  Model    │ │
     │    └────┬────┘ └────┬────┘   │
     │         └─────┬─────┘         │
     │          ┌────▼────┐          │
     │          │  Edge   │          │
     │          │Detector │          │
     │          └────┬────┘          │
     │               └───────┬───────┘
     │                  ┌────▼────┐
     │                  │ Signal  │
     │                  │Generator│
     │                  └────┬────┘
     │                       │
     └───────────┬───────────┴───────────┐
                 │                       │
            ┌────▼────┐            ┌────▼────┐
            │  Risk   │            │Execution│
            │ Manager │            │         │
            └────┬────┘            └────┬────┘
                 │                       │
                 └───────────┬───────────┘
                             │
                    ┌────────▼────────┐
                    │       UI        │
                    │   Console +     │
                    │    Alerts       │
                    └─────────────────┘
```

## Data Flow

### Live Signal Generation

```
1. BRTI Feed
   ├─> Fetches BTC price every 1 second
   ├─> Stores in ring buffer (300 seconds)
   └─> Computes rolling avg60

2. Kalshi Client
   ├─> WebSocket connection for live market data
   ├─> Tracks orderbook updates
   └─> Measures latency

3. Settlement Engine
   ├─> Uses BRTI buffer
   ├─> Computes avg60_A and avg60_B
   └─> Calculates distance to threshold

4. Probability Model
   ├─> Estimates volatility from recent data
   ├─> Runs Monte Carlo simulation (10k paths)
   └─> Outputs P(YES) and P(NO)

5. Edge Detector
   ├─> Compares P(true) to P(market)
   ├─> Applies cost buffers
   ├─> Adjusts for measured latency
   └─> Outputs edge measurements

6. Signal Generator
   ├─> Checks no-trade conditions
   ├─> Evaluates signal types:
   │   ├─> Delay capture
   │   ├─> Momentum confirmation
   │   └─> Baseline gap
   └─> Outputs trade signal

7. Risk Manager
   ├─> Checks circuit breakers
   ├─> Computes position size
   └─> Tracks P&L and drawdown

8. Execution
   ├─> Paper Trader (simulated)
   └─> Live Trader (disabled by default)

9. UI & Alerts
   ├─> Console display (Rich)
   └─> Multi-channel alerts
```

## Key Algorithms

### 1. Settlement Computation

```python
# Convention A: [T-60, T-1] (exclusive of settle moment)
avg60_A = mean(prices[T-60 : T-1])

# Convention B: (T-60, T] (inclusive of settle moment)
avg60_B = mean(prices[T-60 : T])

# Outcome
outcome = "YES" if avg60 > baseline else "NO"
```

### 2. Monte Carlo Probability

```python
for sim in range(num_simulations):
    # Simulate price path using GBM
    path = simulate_gbm(
        S0=current_price,
        steps=seconds_to_settle,
        sigma=volatility_per_second
    )
    
    # Recompute avg60 at settlement
    final_avg60 = compute_avg60_with_path(path)
    
    # Check outcome
    outcomes[sim] = (final_avg60 > baseline)

P_YES = mean(outcomes)
```

### 3. Edge Detection

```python
# Market-implied probability
p_market = best_ask_price  # For buying YES

# True probability from model
p_true = P_YES from Monte Carlo

# Raw edge
edge_raw = p_true - p_market

# Net edge after costs
edge_net = edge_raw - (fee + slippage + latency_buffer)

# Signal if edge_net > threshold
signal = edge_net >= min_edge_threshold
```

### 4. Position Sizing

```python
# Kelly-inspired with constraints
available_budget = min(
    max_risk_per_trade,
    max_open_exposure - current_exposure
)

# Scale with edge
if edge >= target_edge:
    size_fraction = 1.0
elif edge >= min_edge:
    size_fraction = min_size + (1 - min_size) * 
                    (edge - min_edge) / (target_edge - min_edge)
else:
    size_fraction = 0.0

size = available_budget * size_fraction
```

## Performance Optimizations

### 1. Ring Buffer for Price History
- Fixed-size deque (O(1) append)
- No dynamic allocation during runtime
- Fast window queries

### 2. NumPy Vectorization
- All array operations vectorized
- No Python loops for numeric computation
- SIMD instructions utilized

### 3. Numba JIT Compilation
- Monte Carlo simulation compiled to machine code
- ~50-100x speedup vs pure Python
- No overhead after first run

### 4. Async I/O
- All network operations async (aiohttp, websockets)
- Non-blocking concurrent updates
- Multiple data sources in parallel

### 5. Efficient Logging
- Structured JSON logging
- Async file writes
- Separate files by concern

## Fault Tolerance

### 1. Data Source Fallbacks
- BRTI: CF Benchmarks → Exchange composite
- Multiple exchanges for composite
- Automatic failover on errors

### 2. Connection Recovery
- WebSocket auto-reconnect
- Exponential backoff on failures
- State preservation across reconnects

### 3. Circuit Breakers
- Daily loss limit
- Consecutive loss limit with cooldown
- Max drawdown from peak
- Auto-halt on breach

### 4. Validation
- Config validation on startup
- Market data sanity checks
- Model output bounds checking

## Security

### 1. Credential Management
- Config file excluded from git
- Environment variable overrides
- No hardcoded secrets

### 2. API Rate Limiting
- Built-in rate limit awareness
- Exponential backoff on 429
- Request throttling

### 3. Live Trading Safety
- Disabled by default
- Confirmation phrase required
- Multiple kill switches
- All trades logged

## Observability

### 1. Structured Logging
```json
{
  "timestamp": "2026-01-07T12:00:00Z",
  "level": "INFO",
  "logger": "edge_detector",
  "message": "Signal generated",
  "edge_yes": 0.045,
  "edge_no": -0.012,
  "latency_ms": 87
}
```

### 2. Specialized Logs
- `logs/main.log`: General system logs
- `logs/trades.json`: All trade signals/executions
- `logs/latency.json`: Latency measurements
- `logs/signals.json`: Signal history

### 3. Live Metrics
- Console UI refreshes 2x/second
- Real-time P&L tracking
- Performance attribution
- Risk metrics

### 4. Alerts
- Desktop notifications
- Telegram messages
- Webhook integration
- Email (configurable)

## Testing Strategy

### 1. Unit Tests
- Settlement engine accuracy
- Probability model calibration
- Risk manager constraints
- Edge detector logic

### 2. Integration Tests
- Data source connectivity
- End-to-end signal generation
- Order execution flow

### 3. Backtesting
- Historical simulation
- Parameter optimization
- Strategy validation
- Calibration verification

### 4. Paper Trading
- Live execution without risk
- Real-time validation
- Performance tracking

## Deployment Considerations

### 1. Hardware Requirements
- CPU: 2+ cores (Monte Carlo parallelizable)
- RAM: 1GB minimum (ring buffers ~50MB)
- Network: Low latency internet (<50ms to exchanges)
- Storage: 10GB for logs/data

### 2. OS Compatibility
- Linux (recommended for production)
- macOS (development)
- Windows (supported)

### 3. Monitoring
- System health checks
- Latency monitoring
- Error rate tracking
- P&L alerts

### 4. Maintenance
- Log rotation (100MB per file, 10 backups)
- Daily bankroll sync
- Config backups
- Database cleanup (if applicable)

## Future Enhancements

### Potential Additions
1. Machine learning for volatility prediction
2. Multi-market arbitrage detection
3. Options pricing integration
4. Liquidity-aware execution
5. Advanced order types (TWAP, VWAP)
6. Historical data ingestion pipeline
7. Real-time performance dashboard (web)
8. Cloud deployment (AWS/GCP)
9. Database backend for long-term storage
10. API for external integrations

