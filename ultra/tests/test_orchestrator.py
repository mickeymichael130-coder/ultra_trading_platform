"""
Offline end-to-end test of the full trading pipeline (Phase 15).

Feeds synthetic ticks into a real TradingOrchestrator (with a stub broker
and temp DB) and verifies the complete flow: ticks -> candles ->
indicators -> signal -> risk approval -> paper execution -> DB persistence.
No network required.

The candle builder is scoped to the 15m timeframe only so the test runs
fast (the other timeframes are not exercised by the signal path).
"""
import asyncio
import time

import numpy as np
import pytest

from src.broker.deriv_client import Tick
from src.data_engine.candle_builder import CandleBuilder
from src.orchestrator import TradingOrchestrator

SERIES_LEN = 260  # enough past the 200-candle warmup to reach a crossover


class StubBroker:
    """Never touches the network; constructor mirrors DerivClient."""

    def __init__(self, app_id=None, api_token=None, **kwargs):
        self.app_id = app_id
        self.api_token = api_token

    def on_tick(self, handler):
        pass

    def on_candle(self, handler):
        pass

    async def disconnect(self):
        return None


class LifecycleBroker(StubBroker):
    """
    Stub broker supporting the full start() lifecycle: connect, subscribe
    (with canned history), disconnect, and emitting ticks to the handlers.
    """

    def __init__(self, app_id=None, api_token=None, **kwargs):
        super().__init__(app_id=app_id, api_token=api_token)
        self.connected = False
        self.subscriptions = []
        self.history_by_tf = {}
        self._tick_handlers = []

    async def connect(self):
        self.connected = True
        return True

    async def subscribe_ticks(self, symbol):
        self.subscriptions.append(("ticks", symbol))

    async def subscribe_candles(self, symbol, timeframe, history_count=500):
        self.subscriptions.append(("candles", symbol, timeframe))
        return self.history_by_tf.get(timeframe)

    def on_tick(self, handler):
        self._tick_handlers.append(handler)

    def emit_tick(self, tick: Tick):
        for handler in self._tick_handlers:
            handler(tick)


def _history_payload(closes, start_epoch_ms):
    return {
        "candles": [
            {"epoch": start_epoch_ms // 1000 + i * 900, "open": float(c - 0.0005),
             "high": float(c + 0.0005), "low": float(c - 0.0005), "close": float(c),
             "volume": 3}
            for i, c in enumerate(closes)
        ]
    }


def _make_closes(n=SERIES_LEN):
    """Replicate the crossover_candles fixture series (produces real signals)."""
    rng = np.random.default_rng(3)
    pre = np.linspace(0, 0.004, 200) + rng.normal(0, 0.00005, 200).cumsum() * 0.3
    dip = 0.0006 * np.linspace(1, 0, 15)
    rally = np.linspace(0, 0.006, 285)
    close = np.concatenate([1.10 + pre, 1.1040 - dip, 1.1035 + rally])
    return np.abs(close + rng.normal(0, 0.00008, 500).cumsum() * 0.1)[:n]


def _feed_history(orchestrator, symbol, closes, start_epoch_ms):
    """
    Feed 3 ticks per 900s (15m) bucket so the candle builder finalizes one
    candle per bucket with realistic OHLC. Each finalize triggers the full
    signal -> risk -> execution cycle.
    """
    for i, close in enumerate(closes):
        epoch_ms = start_epoch_ms + i * 900_000
        prices = [close - 0.0005, close + 0.0005, close]
        for j, p in enumerate(prices):
            orchestrator._on_tick(Tick(symbol=symbol, price=p, timestamp=epoch_ms + j * 1000))


@pytest.fixture
def orchestrator(tmp_path, monkeypatch):
    orch = TradingOrchestrator(
        symbols=["frxEURUSD"],
        mode="paper",
        db_path=str(tmp_path / "e2e.db"),
        broker_cls=StubBroker,
    )
    # Scope the candle builder to the primary timeframe only (speed).
    builder = CandleBuilder(timeframes=["15m"])
    builder.on_candle_complete(orch._on_candle_complete)
    orch.candle_builder = builder
    # Remove real-time session dependence: always allow trading.
    monkeypatch.setattr(
        builder, "is_session_active",
        lambda symbol=None: {"london": True, "ny": True, "asian": True,
                             "overlap_london_ny": True},
    )
    return orch


@pytest.mark.asyncio
async def test_balance_sync_updates_risk_manager(tmp_path):
    from src.core.domain import Account

    class BalanceBroker(StubBroker):
        async def get_balance(self):
            return Account(broker="stub", balance=2500.0, currency="USD")

    orch = TradingOrchestrator(
        symbols=["frxEURUSD"],
        mode="paper",
        db_path=str(tmp_path / "sync.db"),
        broker_cls=BalanceBroker,
    )
    await orch._sync_balance_once()
    assert orch.risk_manager._current_balance == 2500.0
    assert orch.risk_manager._peak_balance >= 2500.0


@pytest.mark.asyncio
async def test_full_pipeline_end_to_end(orchestrator):
    closes = _make_closes()
    _feed_history(orchestrator, "frxEURUSD", closes, start_epoch_ms=1_750_000_000_000)

    # Let the scheduled paper-fill tasks complete (0.5s simulated fill delay).
    # Poll instead of a fixed sleep so the test is not flaky under load.
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if (orchestrator._stats["trades_executed"] > 0
                and orchestrator.db.get_stats()["trades"] >= orchestrator._stats["trades_executed"]):
            break
        await asyncio.sleep(0.1)
    await asyncio.sleep(0.2)

    stats = orchestrator._stats
    assert stats["ticks_received"] == len(closes) * 3
    assert stats["candles_completed"] == len(closes) - 1
    assert stats["signals_generated"] > 0, "no signals generated"

    # The engineered series must produce an approved trade and execution.
    assert stats["signals_approved"] > 0, "no signal approved by risk"
    assert stats["trades_executed"] > 0, "no trade executed"

    # Everything must be persisted to the database.
    stats_db = orchestrator.db.get_stats()
    assert stats_db["signals"] >= stats["signals_generated"]
    assert stats_db["trades"] >= stats["trades_executed"]

    trades = orchestrator.db.get_trades(limit=1000)
    assert not trades.empty
    assert (trades["status"] == "filled").all()

    # The AI Research Lab note must be persisted with non-HOLD signals.
    signals = orchestrator.db.get_signals(limit=1000)
    assert not signals.empty
    assert signals["reason"].str.contains("AI:", na=False).any()


@pytest.mark.asyncio
async def test_pipeline_persists_state_and_stops(orchestrator):
    _feed_history(orchestrator, "frxEURUSD", _make_closes(), 1_750_000_000_000)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if orchestrator.db.get_stats()["candles"] > 0:
            break
        await asyncio.sleep(0.1)

    assert orchestrator.db.get_stats()["candles"] > 0

    await orchestrator.shutdown()
    assert orchestrator._running is False


@pytest.fixture
def lifecycle_orchestrator(tmp_path, monkeypatch):
    broker = LifecycleBroker()
    # Seed 200 warm-up candles (pre-crossover) so a signal fires as new
    # candles complete during the run.
    closes = _make_closes(n=500)
    broker.history_by_tf["15m"] = _history_payload(closes[:200], 1_750_000_000_000)
    broker.history_by_tf["1h"] = _history_payload(closes[:200], 1_750_000_000_000)

    orch = TradingOrchestrator(
        symbols=["frxEURUSD"],
        mode="paper",
        db_path=str(tmp_path / "lifecycle.db"),
        broker_cls=lambda app_id=None, api_token=None, **kwargs: broker,
    )
    builder = CandleBuilder(timeframes=["15m"])
    builder.on_candle_complete(orch._on_candle_complete)
    orch.candle_builder = builder
    monkeypatch.setattr(
        builder, "is_session_active",
        lambda symbol=None: {"london": True, "ny": True, "asian": True,
                             "overlap_london_ny": True},
    )
    orch.broker = broker
    return orch


@pytest.mark.asyncio
async def test_start_shutdown_full_lifecycle(lifecycle_orchestrator):
    """Runs the real start()/shutdown() lifecycle: connect, subscribe with
    history backfill, live ticks, background loops, and graceful stop."""
    orch = lifecycle_orchestrator

    start_task = asyncio.create_task(orch.start())

    # Wait until start() has subscribed (i.e. history seeded).
    for _ in range(200):
        if len(orch.broker.subscriptions) >= 3:
            break
        await asyncio.sleep(0.05)
    assert orch.broker.connected
    assert len(orch.broker.subscriptions) >= 3

    # The history was backfilled into the candle builder.
    assert len(orch.candle_builder.get_candles("frxEURUSD", "15m")) >= 200

    # Emit the remaining candles of the series so a bullish crossover fires.
    closes = _make_closes(n=500)
    for i, close in enumerate(closes[200:280]):
        epoch_ms = 1_750_000_000_000 + i * 900_000
        for j, p in enumerate([close - 0.0005, close + 0.0005, close]):
            orch.broker.emit_tick(Tick(symbol="frxEURUSD", price=p, timestamp=epoch_ms + j * 1000))

    await asyncio.sleep(1.0)

    assert orch._stats["signals_approved"] > 0, "no signal approved during run"
    assert orch._stats["trades_executed"] > 0, "no trade executed during run"

    # Graceful shutdown must complete and set the shutdown event.
    await orch.shutdown()
    await asyncio.wait_for(start_task, timeout=15)
    assert orch._running is False
    assert orch.db.get_stats()["trades"] >= orch._stats["trades_executed"]
