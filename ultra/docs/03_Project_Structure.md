# 03 — Project Structure

## Current Structure

```text
ultra/
├── main.py                      # entry point: --mode, --broker, --symbols, --db
├── config/
│   └── settings.py              # dataclasses + load_config_from_env()
├── src/
│   ├── orchestrator.py          # TradingOrchestrator — wires all layers
│   ├── broker/
│   │   ├── deriv_client.py      # DerivClient (+ Tick/Candle — to be moved)
│   │   └── binance_client.py    # BinanceClient (token-free market data)
│   ├── data_engine/
│   │   └── candle_builder.py    # ticks → OHLC, session/weekend gate
│   ├── indicators/
│   │   └── technical.py         # IndicatorEngine, MarketSnapshot
│   ├── strategies/
│   │   └── ema_crossover.py     # EMACrossoverStrategy, TradeSignal
│   ├── risk/
│   │   └── manager.py           # RiskManager (10 checks + kill switch)
│   ├── execution/
│   │   └── engine.py            # ExecutionEngine (paper/live), TradeExecution
│   ├── position_manager/
│   │   └── manager.py           # PositionManager (SL/TP/trailing/time exit)
│   ├── database/
│   │   └── manager.py           # DatabaseManager (SQLite)
│   ├── analytics/
│   │   └── reports.py           # win rate, PF, DD, equity, streaks
│   ├── backtesting/
│   │   └── engine.py            # BacktestEngine (same strategy/risk)
│   ├── optimization/
│   ├── monitoring/
│   │   └── health.py            # health checks + API latency
│   ├── dashboard/
│   │   └── app.py               # Streamlit dashboard (Signals shows AI notes)
│   ├── ai_lab/
│   │   ├── market_advisor.py    # regime / momentum / appetite
│   │   └── signal_enhancer.py   # multi-TF confidence + AI research note
│   └── utils/
│       ├── logger.py
│       └── pips.py              # crypto-aware pip sizing
├── tests/                       # 164 tests (pytest)
├── scripts/
│   └── validate_binance_paper.py
├── deploy/                      # start.ps1/.sh, healthcheck, backup
├── docs/                        # this manual
├── BLUEPRINT_CHECKLIST.md       # progress tracker
└── .env / .env.example
```

## Target Structure (UATP)

```text
UniversalTradingPlatform/
├── app/                    # dashboard + widgets
├── brokers/                # base_broker.py, deriv/, binance/, mt5/, paper/, factory.py
├── core/                   # orchestrator, event_bus, execution_engine, trading_engine, domain models
├── market_data/            # tick_buffer, candle_builder, historical_loader, symbol_manager
├── indicators/
├── strategies/
├── risk/
├── portfolio/              # portfolio_manager, allocation, exposure
├── execution/              # order_manager, position_manager, trade_lifecycle
├── backtesting/
├── optimization/
├── database/
├── monitoring/
├── analytics/
├── config/
├── tests/
├── docs/
└── main.py
```

## Mapping (current → target)

| Current `src/…` | Target (UATP) | Notes |
|------------------|---------------|-------|
| `broker/deriv_client.py`, `broker/binance_client.py` | `brokers/deriv/`, `brokers/binance/`, `brokers/base_broker.py`, `brokers/factory.py` | Add `BaseBroker` ABC + factory; adapters translate to/from core models |
| `orchestrator.py` | `core/orchestrator.py`, `core/trading_engine.py` | Orchestrator already selects broker via `broker_cls`/`broker_type` |
| `data_engine/candle_builder.py` | `market_data/candle_builder.py` | Move `Tick`/`Candle` to core domain models |
| `indicators/`, `strategies/`, `risk/` | same (target) | unchanged conceptually; strategy base class to add |
| `execution/engine.py`, `position_manager/` | `execution/order_manager.py`, `execution/position_manager.py`, `core/execution_engine.py` | Split order vs position lifecycle; use core `Order`/`Trade`/`Position` |
| `database/`, `analytics/`, `backtesting/`, `optimization/`, `monitoring/`, `dashboard/`, `ai_lab/`, `utils/` | same (target) | minimal moves; add `portfolio/` layer |
| — | `core/event_bus.py` | new (optional) |
| — | `portfolio/` | new when multi-broker |

## Migration Strategy

The restructure is **incremental, behind the current structure**, not a
big-bang rename:

1. Introduce `src/core/domain` (or `src/domain`) with the broker-neutral models.
2. Introduce `src/broker/base_broker.py` (`BaseBroker` ABC).
3. Point adapters and layers at the core models; keep back-compat aliases so
   the suite stays green each step.
4. Add `portfolio/` and `core/event_bus.py` only when a real need arrives
   (multi-broker / new consumers).

Folder renames only happen once `docs/` phases and tests are aligned — the
physical layout is secondary to the **interface contract**.
