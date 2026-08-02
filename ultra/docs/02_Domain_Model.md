# 02 — Domain Model

Broker-neutral core models. Strategies, risk and execution logic operate on
these objects and **never** on broker-specific types. Each broker adapter
translates between these models and the broker's API.

## The Models

```python
@dataclass
class MarketTick:
    symbol: str
    price: float
    timestamp: int          # epoch ms
    bid: Optional[float] = None
    ask: Optional[float] = None
    pip_size: float = 0.0001
    @property mid -> float
    @property spread -> Optional[float]

@dataclass
class Candle:
    symbol: str
    timeframe: str          # "1m".."1d"
    open: float
    high: float
    low: float
    close: float
    volume: float
    epoch: int              # candle open time, seconds
    def to_dict() -> Dict

@dataclass
class Order:
    symbol: str
    side: str               # BUY | SELL
    quantity: float
    order_type: str         # market | limit | stop
    limit_price: Optional[float] = None
    broker_order_id: Optional[str] = None
    status: str = "pending" # pending | submitted | filled | rejected | cancelled

@dataclass
class Trade:
    symbol: str
    direction: str          # BUY | SELL
    entry_price: float
    exit_price: Optional[float] = None
    position_size: float    # micro lots (normalized risk units)
    stop_loss: float
    take_profit: float
    opened_at: datetime
    closed_at: Optional[datetime] = None
    pnl: Optional[float] = None
    status: str = "open"    # open | closed

@dataclass
class Position:
    symbol: str
    direction: str
    entry_price: float
    quantity: float
    opened_at: datetime
    stop_loss: float
    take_profit: float
    unrealized_pnl: float = 0.0

@dataclass
class Account:
    broker: str
    balance: float
    equity: float
    currency: str
    raw: Dict               # broker-native payload for extra fields

@dataclass
class Signal:
    symbol: str
    direction: str          # BUY | SELL | HOLD
    confidence: float
    timeframe: str
    reason: str
    entry_price: float
    stop_loss: Optional[float]
    take_profit: Optional[float]
    atr_pips: float
```

## Relationship to Existing Types

| UATP model | Where it lives today | Migration plan |
|------------|----------------------|----------------|
| `MarketTick` | `src/core/domain.py` | ✅ **Done** — moved out of `deriv_client.py`; `Tick` kept as back-compat alias; both adapters build `MarketTick`. |
| `Candle` | `src/core/domain.py` | ✅ **Done** — moved to core; adapters normalize broker candles (Deriv epoch seconds; Binance kline ms → seconds). |
| `Signal` | `src/core/domain.py` | ✅ **Done** — was `TradeSignal` (strategies); now `Signal` in core, `TradeSignal = Signal` alias re-exported by `src/strategies/ema_crossover.py`; `SignalEnhancer`, risk and backtest operate on it. |
| `Trade` | `src/core/domain.py` | ✅ **Done** — was `TradeExecution` (execution engine); now `Trade` in core, alias re-exported by `src/execution/engine.py`; `to_dict()` keeps all DB/dashboard fields. |
| `Position` | `src/core/domain.py` | ✅ **Done** — was in `position_manager/manager.py`; now core model (with `ExitReason`), manager owns the state machine; alias re-exported. |
| `Account` | new (target) | ✅ **Model added** to core (`broker`, `balance`, `currency`, `available_balance`, `equity`, `updated_at`). Adapters will build it in the next phase (`get_balance()` on the broker interface). |
| `Order` | Broker-native today (Deriv `buy` contract; Binance order API not used in paper) | New model; paper fills produce an `Order` with status `filled`. |

## Why This Matters

- **Strategies never change when a broker changes.** A `Signal` produced from
  Binance candles is identical in shape to one from Deriv candles.
- **Risk logic reads `Trade`/`Position` uniformly**, so position sizing, stop
  management and kill-switch rules are broker-agnostic.
- **Each adapter is a pure translator.** It owns the only place that knows
  `ticks_history`, `kline_15m`, contracts, order IDs, etc.

## Translation Rules (adapters)

- **Time:** all internal timestamps are epoch **ms** for ticks and epoch
  **seconds** for candles (Deriv native). Adapters convert (e.g. Binance kline
  `openTime` ms → seconds).
- **Price:** always float in quote currency.
- **Quantity/volume:** normalized to base-asset units / micro lots; adapters
  convert broker-native size conventions.
- **Direction:** internal `BUY`/`SELL`/`HOLD`; adapters map to broker
  contract types (Deriv `CALL`/`PUT`, Binance `BUY`/`SELL`).
