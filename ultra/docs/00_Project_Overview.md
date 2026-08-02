# 00 — Project Overview

## Vision

A **broker-agnostic algorithmic trading platform** where the trading logic is
independent of the market or broker. The same strategy, risk rules and
execution flow run on Deriv, Binance, MT5, or any future broker with **zero
changes to the trading engine** — the broker is a plugin behind a common
interface.

We are **not** building a "Deriv bot." We are building a platform the project
can extend for years: add a broker → implement one adapter class; add a
strategy → implement one strategy class.

## Goals

- One strategy/risk/execution stack shared across all brokers.
- Broker adapters are thin: translate the broker's API ↔ broker-neutral domain
  models, nothing else.
- Paper and live trading modes with the same code path.
- Backtesting and parameter optimization reuse the live strategy/risk code.
- Portfolio-level risk management once multiple brokers are active.
- Real-time dashboard, analytics, monitoring, and easy deployment (Windows/Linux).

## Non-Goals (today)

- Order-book / HFT-level execution. Strategy timeframes start at 1m+.
- Built-in regulatory/compliance tooling.
- Machine-learning model *training* in-process (research is a separate track).

## Core Principles

1. **The engine never talks to a broker directly.** It talks to the `Broker Interface`.
2. **Broker-neutral domain models.** `Order`, `Trade`, `Position`, `Account`,
   `MarketTick`, `Candle`, `Signal` are internal; each adapter maps them to/from
   the broker's API.
3. **Layers communicate through interfaces**, not through broker internals.
4. **Event-driven flow** (ticks → candles → signals → risk → execution) with
   optional event bus so new consumers (alerts, analytics, dashboards) attach
   without coupling.
5. **Documentation first.** The `docs/` manual is the spec; code implements it.

## The Loop (definition of progress)

Every iteration runs three criteria against the whole platform:

| Criteria | Question |
|----------|----------|
| **1. Function** | Does it run without errors? (imports, smoke tests, no crashes) |
| **2. Blueprint** | Does it match the spec in `docs/` exactly? (responsibilities present) |
| **3. Quality** | Does it pass tests / risk-safety checks? (pytest, correctness) |

The loop repeats until every phase passes all three. Tracked in
`BLUEPRINT_CHECKLIST.md`.

## Decision Records

### ADR-001 — Broker-agnostic platform (not a Deriv bot)

**Context:** The project began as a Deriv-focused trading bot. The goal is a
single bot that can trade multiple markets (Deriv, Binance, MT5, stocks,
crypto, futures).

**Decision:** Treat the platform as a Universal Algorithmic Trading Platform.
The broker is a plugin behind a `BaseBroker` interface. Engine layers never
import broker-specific types.

**Status:** Adopted. `DerivClient` and `BinanceClient` already share one
interface; formalization as a `BaseBroker` ABC is the next code step.

### ADR-002 — Broker-neutral core domain models

**Context:** Strategy, risk and execution logic currently reference
broker-adjacent types (e.g. `Candle`/`Tick` live in `deriv_client.py`).

**Decision:** Define broker-neutral domain models (`MarketTick`, `Candle`,
`Order`, `Trade`, `Position`, `Account`, `Signal`) in a `core`/`domain` module.
Each broker adapter translates between those and the broker's API. Strategies
and risk logic only ever see the internal models.

**Status:** Adopted. See `02_Domain_Model.md` for the spec and current-state
mapping. Migration is planned as an incremental refactor.

### ADR-003 — Documentation first

**Context:** A 100+ page spec cannot be produced or maintained in chat.

**Decision:** Build the spec as a living Markdown manual in `docs/`. Write the
design before the code; version it with the repo; render to PDF/HTML when
needed. Phases are documented with a fixed template.

**Status:** Adopted. This document set is the first artifact of it.
