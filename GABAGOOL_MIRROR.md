# Gabagool Mirror Bot

Production-grade copy trading system that tracks **@gabagool22** on Polymarket, simulates performance on both Polymarket and Kalshi, and can optionally execute live trades on Kalshi.

## 🎯 What It Does

1. **Tracks gabagool22** - Monitors wallet `0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d` for new trades
2. **Dual Simulation** - Runs two parallel simulations:
   - **Polymarket Exact**: Assumes perfect copy (baseline)
   - **Kalshi Equivalent**: Realistic execution with orderbook depth, latency, slippage
3. **Market Mapping** - Automatically maps Polymarket markets to Kalshi equivalents
4. **Persists Everything** - All signals, orders, fills, positions stored in SQL database
5. **Learns Over Time** - Online learning adjusts thresholds based on performance
6. **Optional Live Execution** - Can route trades to Kalshi (heavily guarded)

## 🚀 Quick Start

### 1. Install Dependencies

```bash
pip install pydantic-settings aiosqlite sqlalchemy[asyncio] numpy
```

### 2. Configure Environment

Create `.env` file:

```bash
# Execution mode
EXECUTION_MODE=SHADOW

# Gabagool wallet
GABAGOOL_WALLET=0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d

# Database (SQLite for local, Postgres for production)
DATABASE_URL=sqlite+aiosqlite:///data/gabagool_mirror.db

# Kalshi API (optional for SHADOW mode)
KALSHI_API_KEY_ID=your-key-id
KALSHI_PRIVATE_KEY_PATH=kalshi_private_key.pem
KALSHI_LIVE_ENABLED=false

# Simulation parameters
DEFAULT_LATENCY_MS=2000
SLIPPAGE_BPS_BUFFER=50
MIN_MAPPING_CONFIDENCE=0.7

# Risk limits
MAX_QTY_SCALE=0.5
MAX_POSITION_USD=50
MAX_TOTAL_EXPOSURE_USD=200
DAILY_LOSS_LIMIT_USD=50
```

### 3. Run Shadow Mode

```bash
python scripts/run_shadow.py
```

This will:
- Connect to Polymarket API
- Poll for gabagool trades every 2 seconds
- Simulate execution on both venues
- Store all data in the database
- Expose metrics on port 8080

## 📊 Modes

### SIM Mode
Replay stored signals without external connections.

```bash
python scripts/run_replay.py --days 7 --delays 2000,5000,10000
```

Output:
```
Latency    | Fill Rate | Partial  | Missed   | Avg Slip
2000ms     |    92.3%  |    5.2%  |    2.5%  |   15.3bps
5000ms     |    85.1%  |    8.4%  |    6.5%  |   23.1bps
10000ms    |    71.2%  |   12.8%  |   16.0%  |   42.7bps
```

### SHADOW Mode
Real-time data, simulated execution.

```bash
python scripts/run_shadow.py
```

### LIVE Mode (⚠️ DANGER)
Real execution on Kalshi. Requires explicit opt-in.

```bash
export KALSHI_LIVE_ENABLED=true
python scripts/run_live.py
# Must type "I UNDERSTAND THE RISKS" to proceed
```

## 🔍 Monitoring

### Health Endpoint
```bash
curl http://localhost:8080/health
```

### Metrics Endpoint
```bash
curl http://localhost:8080/metrics
```

### Status Endpoint
```bash
curl http://localhost:8080/status
```

Key metrics:
- `gabagool_mirror_signals_ingested_total` - Total signals processed
- `gabagool_mirror_kalshi_fill_rate` - Kalshi simulation fill rate
- `gabagool_mirror_slippage_bps` - Slippage histogram
- `gabagool_mirror_pnl_kalshi_sim` - Simulated Kalshi P&L
- `gabagool_mirror_circuit_breaker_state` - Circuit breaker status

## 🏗️ Architecture

```
src/gabagool_mirror/
├── config.py              # Pydantic settings
├── engine.py              # Main orchestrator
├── adapters/
│   ├── base.py            # Abstract interfaces
│   ├── polymarket_adapter.py
│   └── kalshi_adapter.py
├── core/
│   ├── signal.py          # CopySignal dataclass
│   ├── mapping.py         # Market mapping logic
│   └── dedup.py           # Idempotent processing
├── simulation/
│   ├── fill_model.py      # Orderbook fill simulation
│   ├── position.py        # Position ledger
│   ├── polymarket_sim.py  # Exact copy baseline
│   └── kalshi_sim.py      # Realistic Kalshi sim
├── storage/
│   ├── database.py        # Async SQLAlchemy
│   ├── models.py          # DB models
│   └── repository.py      # CRUD operations
├── learning/
│   └── learner.py         # Online parameter optimization
└── ops/
    ├── logger.py          # Structured JSON logging
    ├── metrics.py         # Prometheus metrics
    └── health.py          # Health server
```

## 📦 Database Schema

```sql
-- runs: Execution metadata
-- signals: CopySignals from gabagool
-- mappings: Polymarket -> Kalshi mappings
-- sim_orders: Simulated orders
-- sim_fills: Simulated fills
-- sim_positions: Position ledger
-- outcomes: Market resolutions
-- metrics: Time-series metrics
-- cursors: Ingestion checkpoints
```

## 🎓 How Mapping Works

1. Extract features from Polymarket title:
   - Underlying (BTC/ETH)
   - Contract type (Up/Down 15m)
   - Expiry time

2. Score against available Kalshi markets:
   ```
   score = 0.40 * underlying_match
         + 0.30 * time_proximity
         + 0.20 * contract_type_match
         + 0.10 * strike_similarity
   ```

3. If score >= `MIN_MAPPING_CONFIDENCE`, execute Kalshi simulation

## 🧠 Online Learning

The learner adjusts three parameters:
- `MIN_MAPPING_CONFIDENCE` - How strict to be on mapping
- `SLIPPAGE_BPS_BUFFER` - How much buffer to add to limit orders
- `MAX_QTY_SCALE` - What fraction of gabagool's size to copy

Using contextual bandit with features:
- Spread
- Depth
- Volatility
- Time to expiry
- Recent fill rate
- Recent slippage

Safety bounds prevent catastrophic settings. Circuit breaker activates on:
- 5+ consecutive losses
- 25% drawdown from peak

## ⚠️ Risk Warnings

1. **No Profit Guarantee** - This system does NOT guarantee profits
2. **Latency Matters** - Copy trading degrades rapidly with latency
3. **Liquidity Risk** - Kalshi may not have matching liquidity
4. **Mapping Errors** - Wrong market mapping = wrong trades
5. **API Risk** - Both Polymarket and Kalshi APIs can fail

## 🔧 Development

### Run Tests
```bash
pytest tests/test_gabagool_mirror/ -v
```

### Type Checking
```bash
mypy src/gabagool_mirror/
```

### Database Migration (if using Postgres)
```bash
alembic upgrade head
```

## 📝 Adding New Markets

1. Update `MarketMapping.extract_polymarket_features()` for new title formats
2. Add Kalshi series tickers to `KalshiAdapter.get_markets()`
3. Adjust mapping weights if needed

## 🐳 Docker

```bash
docker-compose up -d
```

Services:
- `gabagool-mirror`: Main application
- `postgres`: Database (production)
- `adminer`: Database UI

## 📄 License

MIT - Use at your own risk.

