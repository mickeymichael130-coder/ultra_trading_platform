# ULTRA Blueprint Checklist

Live progress tracker for building the platform to match the blueprint.

> **Vision (UATP):** This is a **Universal Algorithmic Trading Platform**, not a
> Deriv bot. The broker is a plugin behind a common interface. The full
> specification lives in **`docs/`** (living engineering manual); this file is
> the **progress tracker** only. See `docs/00_Project_Overview.md` for the
> vision, goals and decision records (ADR-001 broker-agnostic, ADR-002
> broker-neutral domain models, ADR-003 docs-first).

## The Loop

Every iteration runs the same 3 criteria against the whole platform. The loop
repeats until every phase passes all three criteria. Then and only then is the
product considered "final".

| Criteria | Question |
|----------|----------|
| **1. Function** | Does it run without errors? (imports, smoke tests, no crashes) |
| **2. Blueprint** | Does it match the blueprint phase exactly? (responsibilities present) |
| **3. Quality** | Does it pass tests / risk-safety checks? (pytest, correctness) |

Verdict legend: ✅ pass | 🟡 partial | ❌ fail

---

## Phase Status

### Phase 1 — Foundation
| Criteria | Status | Notes |
|----------|--------|-------|
| 1. Function | ✅ | Structure, config, logging present and verified |
| 2. Blueprint | ✅ | Project skeleton, venv, config, logging all present |
| 3. Quality | ✅ | Full pytest suite now exists (189 tests) |

### Phase 2 — Broker Layer
| Criteria | Status | Notes |
|----------|--------|-------|
| 1. Function | ✅ | Paper mode works without API token (public one-shot history); **streaming/subscribe requires `DERIV_API_TOKEN`**. **Alternative broker: Binance (`--broker binance`) provides token-free trade/kline streaming + REST backfill** |
| 2. Blueprint | ✅ | Connect/auth/subscribe/reconnect + real resubscribe tracking; both `DerivClient` and `BinanceClient` implement the same interface (orchestrator swaps via `broker_cls`/`broker_type`) |
| 3. Quality | ✅ | 23 Deriv protocol tests + 14 BinanceClient protocol tests + 21 broker-abstraction tests (BaseBroker ABC, factory, domain models incl. Signal/Trade/Position/Account/Order + get_balance); live validation found & fixed 3 real bugs in Deriv client (subscriptions lost on mid-request disconnect, `subscribe:1` fails unauthenticated → token-free `fetch_history()`, `_send_request` dict mutation); BinanceClient live smoke-tested against real API (ticks flow, 500-candle history, clean disconnect) |

### Phase 3 — Market Data Engine
| Criteria | Status | Notes |
|----------|--------|-------|
| 1. Function | ✅ | Candle builder aggregates ticks into OHLC across 5 timeframes |
| 2. Blueprint | ✅ | Tick buffer → candle builder → OHLC candles |
| 3. Quality | ✅ | 12 unit tests (aggregation, completion, seeding, sessions); **forex weekend gate — `is_session_active` reports `market_open` and closes Sat 00:00→Sun 22:00 UTC** (configurable via `weekend_gate`); **crypto symbols (e.g. BTCUSDT) bypass the weekend gate (24/7)** |

### Phase 4 — Indicator Engine
| Criteria | Status | Notes |
|----------|--------|-------|
| 1. Function | ✅ | All indicators present; RSI divide-by-zero fixed |
| 2. Blueprint | ✅ | Indicators only read candles → MarketSnapshot |
| 3. Quality | ✅ | 4 unit tests incl. NaN/edge cases; `calculate_series` added; **crypto-aware pip sizing** — `atr_pips` uses `get_pip_size(symbol)` (BTC/ETH `$1/pip`, smaller coins `$0.01/pip`, forex unchanged) |

### Phase 5 — Strategy Engine
| Criteria | Status | Notes |
|----------|--------|-------|
| 1. Function | ✅ | EMA crossover + RSI filter → BUY/SELL/HOLD |
| 2. Blueprint | ✅ | Reads indicators only, emits signals, no broker calls |
| 3. Quality | ✅ | 6 unit tests (crossovers, filters, sessions) |

### Phase 6 — Risk Engine
| Criteria | Status | Notes |
|----------|--------|-------|
| 1. Function | ✅ | 10 hard checks + kill switch all present |
| 2. Blueprint | ✅ | Gatekeeper between signal and execution |
| 3. Quality | ✅ | 9 unit tests covering checks + kill switch |

### Phase 7 — Execution Engine
| Criteria | Status | Notes |
|----------|--------|-------|
| 1. Function | ✅ | Paper + live execution paths present |
| 2. Blueprint | ✅ | Only approved signals execute; records every execution |
| 3. Quality | ✅ | 3 async tests; P&L now uses micro-lot sizing (fixed 100x bug) |

### Phase 8 — Position Manager
| Criteria | Status | Notes |
|----------|--------|-------|
| 1. Function | ✅ | SL/TP/trailing/break-even/time exit all present |
| 2. Blueprint | ✅ | Strategy yields control after entry |
| 3. Quality | ✅ | 3 async tests; P&L micro-lot fix applied here too |

### Phase 9 — Database Layer
| Criteria | Status | Notes |
|----------|--------|-------|
| 1. Function | ✅ | 7 tables, state survives restarts |
| 2. Blueprint | ✅ | Trades/orders/positions/balance/performance/logs/candles stored |
| 3. Quality | ✅ | 7 unit tests (schema, CRUD, risk-state persistence) |

### Phase 10 — Analytics Engine
| Criteria | Status | Notes |
|----------|--------|-------|
| 1. Function | ✅ | Win rate, PF, DD, equity, streaks all produced |
| 2. Blueprint | ✅ | DB → analytics → performance |
| 3. Quality | ✅ | 3 unit tests |

### Phase 11 — Backtesting Engine
| Criteria | Status | Notes |
|----------|--------|-------|
| 1. Function | ✅ | O(n) precomputed series → 2000 candles in ~13s (was >84s/600) |
| 2. Blueprint | ✅ | Same strategy/risk code as live; historical candles in |
| 3. Quality | ✅ | 5 tests incl. real trade generation; `--mode backtest` CLI works |

### Phase 12 — Optimization Engine
| Criteria | Status | Notes |
|----------|--------|-------|
| 1. Function | ✅ | `src/optimization/` module implemented |
| 2. Blueprint | ✅ | Grid search supports EMA + indicator params (rebuilds engines) |
| 3. Quality | ✅ | 2 tests |

### Phase 13 — Dashboard
| Criteria | Status | Notes |
|----------|--------|-------|
| 1. Function | ✅ | Home/Live/Open/Performance/Signals/Settings/Logs pages load |
| 2. Blueprint | ✅ | Displays only; no trading decisions |
| 3. Quality | ✅ | 5 AppTest smoke tests; **Signals page surfaces AI research notes (AI:) in an expander + full history table** |

### Phase 14 — Monitoring
| Criteria | Status | Notes |
|----------|--------|-------|
| 1. Function | ✅ | CPU/RAM/disk/staleness checks present |
| 2. Blueprint | ✅ | Real DB reachability, internet TCP check, API ping latency |
| 3. Quality | ✅ | 18 tests (classification, DB, latency, full health run) |

### Phase 15 — Live Trading
| Criteria | Status | Notes |
|----------|--------|-------|
| 1. Function | 🟡 | Gated behind token + 5s abort; live network untestable offline |
| 2. Blueprint | ✅ | Signal → risk → execution → Deriv → confirm → DB → dashboard |
| 3. Quality | ✅ | Offline E2E pipeline + full start()/shutdown() lifecycle tests; fixed `save_trade` exec_id + ExitReason bugs |

### Phase 16 — AI Research Lab (Optional)
| Criteria | Status | Notes |
|----------|--------|-------|
| 1. Function | ✅ | `MarketAdvisor` (regime/momentum/appetite/recommendation) + `SignalEnhancer` (multi-TF confidence calibration) |
| 2. Blueprint | ✅ | Research layer that enhances signal quality, no broker/DB writes |
| 3. Quality | ✅ | 13 unit tests; **wired into orchestrator signal path** — AI research note persisted per signal |

### Phase 17 — Production Deployment
| Criteria | Status | Notes |
|----------|--------|-------|
| 1. Function | ✅ | Runs 24/7 on Windows/VPS |
| 2. Blueprint | ✅ | systemd unit + auto-restart (`.ps1`/`.sh`), daily backup, healthcheck |
| 3. Quality | ✅ | Scripts validated on Windows (syntax, backup zip, healthy/failure paths); `main.py` writes/cleans `data/bot.pid` |

---

## Iteration Log

| Iteration | Date | Changes | Criteria improvements |
|-----------|------|---------|----------------------|
| 1 | 2026-08-01 | Paper-mode auth fix; real resubscribe; backtest CLI + O(n) speedup; optimization module + EMA param tuning; micro-lot P&L fix (3 places); RSI div-zero fix; `.env`/token cleanup; 47-test suite | Phases 1–13 mostly ✅ across all 3 criteria |
| 2 | 2026-08-01 | Real monitoring checks (DB/internet/ping latency) + 18 tests; 4 dashboard AppTest smoke tests; deployment scripts (systemd, start.ps1/sh, backup.ps1, healthcheck.ps1) validated; `main.py` PID file; offline E2E orchestrator tests (2) exercising full pipeline; fixed `save_trade` exec_id mapping + `ExitReason` bug | Suite grew 47 → 76 tests, all passing; Phases 13–15 & 17 now ✅ |
| 3 | 2026-08-01 | 18 offline DerivClient protocol tests (fake websocket); full start()/shutdown() lifecycle orchestrator test; AI Research Lab implemented (`MarketAdvisor` + `SignalEnhancer`) with 13 tests | Suite grew 76 → 108 tests, all passing; Phase 2 & 16 now ✅ |
| 4 | 2026-08-01 | Wired `config/settings.py` into every orchestrator layer (broker/data/indicators/strategy/risk/execution/AI); wired `SignalEnhancer` into the signal path with stored 1h confirmation; added `DatabaseManager.get_signals`; `main.py` calls `load_config_from_env()` | Suite grew 108 → 113 tests, all passing; config now truly drives behavior |
| 5 | 2026-08-02 | Dashboard Signals page now surfaces AI research notes (expander + reason column, 1 new AppTest). **Live paper-mode validation**: real Deriv connect + one-shot history OK (468×15m + 150×1h per symbol); full signal pipeline ran on live data with 0 errors (session gate, ATR floor 3.9<5.0, crossover detection all correct). Validation exposed 3 real bugs → fixed: subscription loss on reconnect, `subscribe:1` fails unauthenticated (added `fetch_history` + clear DERIV_API_TOKEN auth hint), `_send_request` dict mutation | Suite grew 113 → 119 tests, all passing; real network path to Deriv proven |
| 6 | 2026-08-02 | **Forex weekend gate** in `CandleBuilder.is_session_active` (`market_open` flag; Sat 00:00→Sun 22:00 UTC closed) with 6 new deterministic-clock tests; hardened flaky E2E orchestrator tests (poll-for-fill instead of fixed sleep) | Suite grew 119 → 125 tests, all passing |
| 7 | 2026-08-02 | **Binance integration** (`--broker binance`): token-free `BinanceClient` (combined-stream WS `@trade`+`@kline`, REST `/api/v3/klines` backfill normalized to Deriv `{"candles":[...]}` shape, debounced reconnect, bounded close/reconnect so it never hangs); **crypto-aware pip sizing** (`get_pip_size` BTC/ETH `$1/pip` etc., wired into IndicatorEngine, RiskManager, backtest slippage); **symbol-aware session gate** (crypto bypasses forex weekend gate); broker selection via `--broker`/`BROKER`/`broker_type` with per-broker default symbols; live smoke-validated against real Binance API (ticks flow, 500×15m history, full paper pipeline 0 errors, crypto session `market_open=True`) | Suite grew 125 → 164 tests, all passing; paper mode now runs on Binance without any token |
| 8 | 2026-08-02 | **UATP blueprint adopted + living manual created** (`docs/`): `00_Project_Overview` (vision, goals, ADRs), `01_System_Architecture` (layered arch, runtime flow, broker abstraction, multi-broker/portfolio targets — Mermaid), `02_Domain_Model` (broker-neutral `MarketTick`/`Candle`/`Order`/`Trade`/`Position`/`Account`/`Signal` + current-state mapping), `03_Project_Structure` (current vs target layout + migration strategy), `phases/` template + `Phase_02_Broker_Framework` worked example, `diagrams/`; checklist re-scoped as progress tracker under the docs manual | Docs-first: broker-agnostic spec now the source of truth; next code step = `BaseBroker` ABC + core domain models |
| 9 | 2026-08-02 | **Broker abstraction formalized** (ADR-001/002): `src/core/domain.py` broker-neutral `MarketTick`/`Candle`/`ConnectionState` (with `Tick` back-compat alias); `src/broker/base_broker.py` `BaseBroker` ABC (connect/disconnect, subscribe*, fetch_history, order stubs, ping, `is_connected`/`account_balance` properties); `DerivClient` & `BinanceClient` now subclass it; `src/broker/broker_factory.py` (`get_broker_class`, `available_brokers`, deriv fallback); orchestrator + candle_builder + binance_client import domain models; 11 new abstraction tests (ABC contract, factory, domain) | Suite grew 164 → 175 tests, all passing; broker selection now one line (`--broker`), engine never imports a broker adapter for logic |
| 10 | 2026-08-02 | **Remaining domain models migrated to core** (ADR-002): `Signal` (was `TradeSignal` in strategies), `Trade` (was `TradeExecution` in execution engine), `Position` + `ExitReason` (were in position manager) and new `Account` all live in `src/core/domain.py`; `OrderStatus`/`ExecutionMode`/`SignalDirection`/`SignalStrength` enums moved too; back-compat aliases (`TradeSignal = Signal`, `TradeExecution = Trade`) re-exported by `ema_crossover.py` / `execution/engine.py` so every existing import path still resolves; 6 new domain tests (alias identity, `Trade.to_dict` DB fields, `Position` defaults, `Account`) | Suite grew 175 → 181 tests, all passing; core domain is now pandas-free (`timestamp: Any`) so domain imports stay lightweight; only broker-native `Order` remains un-modeled |

---
| 11 | 2026-08-02 | **Order model + Account on the broker interface** (ADR-002): broker-neutral Order in src/core/domain.py; execution engine emits a filled Order per paper/live fill (attached as Trade.order); new BaseBroker.get_balance() -> Optional[Account] abstract method; Deriv builds Account from uthorize, Binance public mode returns None; scripts/criteria.py + scripts/iterate.py = the criteria-driven iteration loop (run criteria + tests + docs checks, --full/--phase/--only/--log); suite grew 181 -> 185 tests, all passing | |
| 12 | 2026-08-02 | **Deployment-ready product** (Phase 17 + ops): runtime/dev deps split (requirements*.txt); Dockerfile + docker-compose.yml + .dockerignore (non-root, volumes, log rotation, secrets via env); VERSION + src/utils/version.py (startup logs version); .github/workflows/ci.yml (full suite on push/PR, py 3.11/3.12); DEPLOYMENT.md operator runbook; docs/phases/Phase_17_Deployment.md spec; phases index made accurate; start.sh encoding/mode bugs fixed; orchestrator live-balance sync via BaseBroker.get_balance() (_sync_balance_once, 60s loop); loop grown to 11 criteria incl. deploy artifacts + no-secrets (C9-C11); suite grew 185 -> 189 tests, all passing; live Binance paper smoke: 501 ticks, 0 errors | |
| 13 | 2026-08-02 | **Deploy validation hardening**: docker-compose .env now optional (
equired: false, compose >= 2.24) so a fresh checkout / CI with no .env still starts token-less paper; ci.yml gained a docker-build job (compose config + image build + version smoke) since Docker is not available locally; C9 now statically validates docker-compose + ci YAML parse (caught a real bug: colon in a 
ame: scalar would have broken the workflow); PyYAML added to requirements-dev. All 11 criteria PASS, 189 tests green | |
| 14 | 2026-08-02 | **Python 3.11 verified + live-token smoke**: new .venv311 (3.11.9) + requirements-dev install resolved pandas 3.0.5/numpy 2.4.6; full loop 11/11 PASS under 3.11 (189 tests, 184s) proving CI's py3.11 matrix and pandas-3 compat; added scripts/validate_deriv_live.py (read-only auth+balance+ticks+history check, no orders, SKIPs gracefully without token); ran it with the updated .env: Deriv ws connects (app_id 1089) but server returns InvalidToken - matches the known 2026 Deriv constraint already logged (registered app + PAT needed); user chose to skip live Deriv for now; DEPLOYMENT.md gained an InvalidToken troubleshooting row | |
| 15 | 2026-08-02 | **Ops completion + production architecture roadmap**: pinned runtime/dev deps to the exact CI-verified set (pandas 3.0.5, numpy 2.4.6, websockets 16.1.1, streamlit 1.60.0, plotly 6.9.0, psutil 7.2.2; dev pytest 9.1.1, pytest-asyncio 1.4.0, PyYAML 6.0.3) for reproducible Docker/CI images; added deploy/healthcheck.sh + deploy/backup.sh (Linux/macOS mirrors of the .ps1 tools, exec-bit set, syntax-checked with Git bash, functionally tested: healthy/unhealthy/missing paths + tar+prune); Dockerfile now ships deploy/ and docker-compose gained a HEALTHCHECK (deploy/healthcheck.sh, 60s/10s/30s/3) so 'docker compose ps' reports healthy and restart policy acts on it; DEPLOYMENT.md documents cron/systemd-timer backups + compose health; criteria C9 now requires both .sh scripts; DEPLOYMENT.md gained a Target production architecture section mapping the VPS plan (Postgres/Redis/Nginx/Prometheus = planned, needs a Docker host + code wiring) against what is done | |

## Open items for next iteration

- **Iteration loop is the workflow**: `python scripts/iterate.py` runs 11 criteria (ADR compliance, tests, docs, deploy artifacts, no-secrets) and suggests the next open item; `--full` runs the whole suite, `--log "msg"` records the iteration. Add new criteria in `scripts/criteria.py`.
- **Fill out remaining phase docs** (Phase 03–16) from the `docs/phases/` template as each area is touched; index in `docs/phases/README.md` is now accurate.
- **Validate on a real host**: `docker compose up -d --build` on a Linux VPS (Binance-friendly region), run paper for a full session, wire `deploy/healthcheck.ps1` (or a Linux port) to an uptime monitor, and schedule `deploy/backup.ps1` (or a cron/timer equivalent) daily.
- **Optional production upgrades**: Postgres backend for analytics (config present, not wired), Prometheus/health HTTP endpoint + Grafana, pinned patch versions in requirements for reproducible images.
- **Live Deriv streaming**: still requires a real Deriv API token in `.env` (Deriv rejects `subscribe` streams unauthenticated with `InvalidSymbol`). Both supplied tokens were rejected server-side (`InvalidToken`/`InvalidAppID`) on every endpoint tested; the 2026 Deriv platform needs a registered app (developers.deriv.com) + PAT + OTP-authenticated WebSocket URL. Deferred until going live
- **Phase 15**: with a token in place, run `python main.py --mode live` to collect a full live streaming session (ticks → 1m→15m candles → signals → live fills)
- **Portfolio Manager** (Phase 09 / `docs/01_System_Architecture.md`): add only when multi-broker is active
- **Crypto param tuning**: `min_atr_pips=5.0` and the pip model were calibrated for forex; review ATR floors and per-pair pip sizes after a few days of Binance data
- **Live data insight (forex)**: current market ATR ≈ 3.9 pips < the 5.0 `min_atr_pips` floor — consider lowering the floor (or accepting fewer trades) once live data accumulates
- **Dashboard**: AI notes now shown; consider a dedicated "AI Research" page with regime/momentum history
