# 01 — System Architecture

## Layered Architecture

```mermaid
graph TD
    subgraph APP["Application Layer"]
        DASH["Dashboard (Streamlit)"]
        CLI["main.py / CLI"]
    end

    subgraph CORE["Trading Core"]
        ORCH["Trading Orchestrator"]
        STRAT["Strategy Engine"]
        RISK["Risk Engine"]
        EXEC["Execution Engine"]
    end

    subgraph DATA["Market Data"]
        CB["Candle Builder"]
        IND["Indicator Engine"]
        SNAPSHOT["MarketSnapshot"]
    end

    subgraph BROKER["Broker Layer"]
        BI["Broker Interface (BaseBroker)"]
        DERIV["DerivClient"]
        BIN["BinanceClient"]
        PAPER["PaperBroker (simulated fills)"]
    end

    subgraph PERSIST["Persistence"]
        DB[("SQLite (database)")]
    end

    DASH --> ORCH
    CLI --> ORCH
    ORCH --> STRAT
    ORCH --> RISK
    ORCH --> EXEC
    ORCH --> CB
    CB --> IND
    IND --> SNAPSHOT
    STRAT --> SNAPSHOT
    EXEC --> BI
    CB -. historical seed .-> BI
    BI --> DERIV
    BI --> BIN
    BI --> PAPER
    EXEC --> DB
    ORCH --> DB
    DASH --> DB
```

**Current state:** Deriv and Binance clients already implement the same
informal interface and are swapped via the orchestrator's `broker_cls` /
`broker_type` selection. The `BaseBroker` ABC (formal contract) is the next
code step.

## Runtime Flow

```mermaid
sequenceDiagram
    participant M as Market
    participant B as Broker Adapter
    participant CB as Candle Builder
    participant I as Indicator Engine
    participant S as Strategy Engine
    participant R as Risk Engine
    participant E as Execution Engine
    participant DB as Database

    M->>B: tick / kline update
    B->>CB: MarketTick
    CB->>I: completed Candle (15m)
    I->>S: MarketSnapshot (indicators)
    S->>S: generate_signal(snapshot, session)
    S->>R: TradeSignal (BUY/SELL/HOLD)
    R->>R: evaluate(signal, equity)
    alt approved
        R->>E: approved signal
        E->>B: place_order (paper: simulated)
        B-->>E: fill / order state
        E->>DB: persist execution + trade
    else rejected
        R-->>S: reject (reason recorded)
    end
    DB-->>DASH: signals / trades / positions
```

## Broker Abstraction

The trading engine never imports a broker-specific class for logic. It depends
on the `BaseBroker` contract:

```mermaid
graph LR
    subgraph BIF["Broker Interface (BaseBroker)"]
        CONN["connect / disconnect"]
        SUB["subscribe_ticks / subscribe_candles / fetch_history"]
        DATA["on_tick / on_candle handlers"]
        ORD["place_order / close_order (future)"]
        ACC["get_balance / account (future)"]
    end
    DERIV["DerivClient"] --> BIF
    BIN["BinanceClient"] --> BIF
    PAPER["PaperBroker"] --> BIF
```

Both adapters today:

| Capability | DerivClient | BinanceClient |
|------------|-------------|---------------|
| connect / disconnect | ✅ | ✅ |
| subscribe_ticks | ✅ (needs token for stream) | ✅ (token-free) |
| subscribe_candles | ✅ (needs token for stream) | ✅ (REST backfill + kline stream) |
| fetch_history (one-shot) | ✅ | ✅ |
| on_tick / on_candle / on_error | ✅ | ✅ |
| reconnect / resubscribe | ✅ | ✅ (debounced) |
| order placement | ✅ (contract model) | stubbed (paper data broker) |
| auth | token optional (paper) | none (public) |

**Key rule:** any engine-layer code that touches data uses
`MarketTick`/`Candle` (internal models). Adapters own the translation.

## Event Flow (target)

```mermaid
graph LR
    T["TickReceived"] --> MD["Market Data Updated"]
    MD --> SG["Signal Generated"]
    SG --> RA["Risk Approved"]
    RA --> OE["Order Executed"]
    OE --> PU["Position Updated"]
    PU --> TC["Trade Closed"]
```

Consumers (alerts, analytics, dashboard, monitoring) subscribe to these events
without the producers knowing about them. The event bus is an optional
enhancement; the current pipeline is direct method calls, which is fine at this
scale — the flow must be preserved so the bus can be layered on later.

## Multi-Broker (target)

```mermaid
graph TD
    ORCH2["Trading Orchestrator"]
    ORCH2 --> D2["DerivBroker (frx pairs)"]
    ORCH2 --> B2["BinanceBroker (BTCUSDT, ETHUSDT)"]
    ORCH2 --> M2["MT5Broker (EURUSD)"]
    PM["Portfolio Manager"] --> ORCH2
    PM --> ACCT1["Deriv Account $2,000"]
    PM --> ACCT2["Binance Account $3,000"]
    PM --> ACCT3["MT5 Account $5,000"]
```

Each broker keeps its own connection, market data, orders and positions. The
orchestrator coordinates them; the **Portfolio Manager** (new layer) allocates
capital, aggregates account value, enforces global exposure limits and produces
consolidated reports.

## Portfolio Layer (future, Phase 09)

Responsibilities:

- Capital allocation between brokers.
- Total account value / equity aggregation.
- Global risk limits (max daily loss, drawdown, exposure) across accounts.
- Correlation guard — avoid overexposure to the same underlying across brokers.
- Consolidated performance reporting.

Until multi-broker is active, the `RiskManager` enforces per-account limits and
the portfolio layer is a thin wrapper.
