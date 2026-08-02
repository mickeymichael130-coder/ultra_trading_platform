# 🚀 ULTRA Algorithmic Trading Platform

Broker-neutral algorithmic trading platform (Deriv forex + Binance crypto).
Built with production-grade architecture: broker abstraction, isolated layers,
state persistence, hard risk constraints, and docs-first governance.

## Deployment & Operations

See [DEPLOYMENT.md](DEPLOYMENT.md) for the operator runbook — Docker
(recommended), systemd, Windows supervisor, healthchecks, backups and upgrades.
The platform spec lives in [docs/](docs/). Version: `VERSION`.

## Development Loop

Iterate against the blueprint (docs-first):

```bash
python scripts/iterate.py            # criteria C1–C11 + fast tests
python scripts/iterate.py --full     # + full test suite
python scripts/iterate.py --log "…"  # record an iteration in the checklist
```

## Architecture

```
User
  │
  ▼
ULTRA Dashboard (Streamlit)
  │
  ▼
Trading Orchestrator
  │
  ├── Broker Layer (Deriv WebSocket API)
  ├── Data Engine (Multi-timeframe OHLC)
  ├── Indicator Engine (EMA, RSI, ATR, MACD, BB, ADX)
  ├── Strategy Engine (Signal Generation)
  ├── Risk Engine ⭐ (10 Hard Checks, Kill Switch)
  ├── Execution Engine (Paper/Live)
  ├── Position Manager (SL, TP, Trailing, Break-Even)
  ├── Database Layer (SQLite Persistence)
  ├── Analytics Engine (Performance Reports)
  └── Monitoring (Health Checks, Alerts)
```

## Quick Start

### 1. Setup

```bash
# Clone and enter directory
cd ultra

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your credentials
```

### 2. Paper Trading (Recommended First)

```bash
export DERIV_APP_ID=1089
export TRADING_MODE=paper
export LOG_LEVEL=INFO

python main.py --mode paper
```

> Paper mode streams public market data and needs **no API token**. For live
> trading you must set `DERIV_API_TOKEN` to your real token.

### 3. Launch Dashboard (Separate Terminal)

```bash
streamlit run src/dashboard/app.py
```

### 4. Live Trading (⚠️ Real Money)

```bash
export DERIV_API_TOKEN=<your_api_token>
export TRADING_MODE=live

python main.py --mode live
```

## Configuration

All settings in `config/settings.py`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| Initial Capital | $2,000 | Starting balance |
| Max Risk/Trade | 1.5% ($30) | Hard limit per position |
| Max Daily Loss | 3% ($60) | Daily circuit breaker |
| Max Drawdown | 10% ($200) | Kill switch trigger |
| Max Open Trades | 2 | Concurrent positions |
| Cooldown | 15 min | Post-loss waiting period |
| Timeframes | 1m/5m/15m/30m/1h | Multi-timeframe analysis |
| Symbols | EUR/USD, GBP/USD, USD/JPY, AUD/USD | Major forex pairs |

## Project Structure

```
ultra/
├── config/
│   └── settings.py              # All configuration
├── src/
│   ├── broker/
│   │   └── deriv_client.py      # WebSocket API client
│   ├── data_engine/
│   │   └── candle_builder.py    # OHLC aggregation
│   ├── indicators/
│   │   └── technical.py         # Technical analysis
│   ├── strategies/
│   │   └── ema_crossover.py     # Signal generation
│   ├── risk/
│   │   └── manager.py           # Risk management (gatekeeper)
│   ├── execution/
│   │   └── engine.py            # Order execution
│   ├── position_manager/
│   │   └── manager.py           # Trade monitoring
│   ├── database/
│   │   └── manager.py           # SQLite persistence
│   ├── analytics/
│   │   └── reports.py           # Performance analytics
│   ├── monitoring/
│   │   └── health.py            # System health checks
│   ├── dashboard/
│   │   └── app.py               # Streamlit UI
│   ├── backtesting/
│   │   └── engine.py            # Strategy backtesting
│   ├── utils/
│   │   └── logger.py            # Structured logging
│   └── orchestrator.py          # Main engine
├── main.py                      # Entry point
├── requirements.txt
└── .env.example
```

## Risk Management

**Hard Constraints (Non-Negotiable):**

| Check | Threshold | Action |
|-------|-----------|--------|
| Kill Switch | 10% drawdown ($200) | Permanent halt, manual reset |
| Daily Loss | 3% ($60) | Reject new trades |
| Per-Trade Risk | 1.5% ($30) | Reject oversized positions |
| Max Open Trades | 2 | Reject if at limit |
| Daily Trade Limit | 6 | Reject if at limit |
| Cooldown | 15 min after loss | Reject during cooldown |
| Correlation | 1 per group | Reject correlated pairs |
| Confidence | < 0.60 | Reject weak signals |
| Session | London + NY only | Reject Asian session |
| Stop Loss | Missing or invalid | Reject unprotected trades |

## Database Schema

7 tables with full audit trail:
- `candles` - OHLC history
- `trades` - Complete trade journal
- `balance` - Balance snapshots
- `risk_state` - Persisted risk manager state
- `signals` - All signals (approved + rejected)
- `performance` - Daily metrics
- `system_logs` - Structured logs

State survives restarts — risk manager recovers from database on startup.

## Backtesting

```python
from src.backtesting.engine import BacktestEngine

engine = BacktestEngine(initial_capital=2000)
result = engine.run(candles_df, symbol="frxEURUSD", timeframe="15m")

print(f"Trades: {result.total_trades}")
print(f"Win Rate: {result.win_rate:.1f}%")
print(f"Net P&L: ${result.net_pnl:.2f}")
print(f"Max DD: {result.max_drawdown_pct:.1f}%")
```

## Optimization

```python
results = engine.optimize(
    candles_df,
    symbol="frxEURUSD",
    param_grid={
        "ema_fast": [8, 12, 16],
        "ema_slow": [21, 26, 30],
        "rsi_overbought": [65, 70, 75],
        "rsi_oversold": [25, 30, 35]
    }
)
```

## Safety

- Always start with **paper mode**
- Minimum 2 weeks paper validation before live
- Kill switch requires **manual reset** after activation
- All trades logged with full audit trail
- Database persists state across restarts

## License

Proprietary. For personal use only.
