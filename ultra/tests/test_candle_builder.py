"""
Tests for Phase 3 — Market Data Engine (CandleBuilder).
"""
from datetime import datetime, timezone

import pytest

from src.broker.deriv_client import Tick, Candle
from src.data_engine.candle_builder import CandleBuilder


class FakeDateTime:
    """Stand-in for datetime whose now() returns a fixed UTC time."""
    fixed = None

    @classmethod
    def now(cls, tz=None):
        return cls.fixed


def make_tick(symbol="frxEURUSD", price=1.1000, epoch_s=1_700_000_000):
    return Tick(
        symbol=symbol,
        price=price,
        timestamp=epoch_s * 1000,
        bid=price - 0.0001,
        ask=price + 0.0001,
    )


def test_builds_candles_across_timeframes():
    builder = CandleBuilder(timeframes=["1m", "5m"])
    builder.register_symbol("frxEURUSD")

    # 3 ticks across a 1m boundary
    builder.on_tick(make_tick(price=1.1000, epoch_s=1_700_000_000))
    builder.on_tick(make_tick(price=1.1005, epoch_s=1_700_000_000 + 30))
    builder.on_tick(make_tick(price=1.1002, epoch_s=1_700_000_060))

    df = builder.get_candles("frxEURUSD", "1m")
    assert len(df) >= 2
    # Completed candle (ticks at epoch 1700000000 and +30s)
    assert df.iloc[0]["open"] == 1.1000
    assert df.iloc[0]["high"] == 1.1005
    assert df.iloc[0]["low"] == 1.1000
    assert df.iloc[0]["close"] == 1.1005
    # Current (incomplete) candle started by the tick at +60s
    assert df.iloc[-1]["close"] == 1.1002


def test_tick_aggregation_updates_high_low():
    builder = CandleBuilder(timeframes=["1m"])
    builder.register_symbol("frxEURUSD")

    builder.on_tick(make_tick(price=1.1000, epoch_s=1_700_000_000))
    builder.on_tick(make_tick(price=1.1020, epoch_s=1_700_000_010))
    builder.on_tick(make_tick(price=1.0990, epoch_s=1_700_000_020))

    current = builder.get_latest_candle("frxEURUSD", "1m")
    assert current.high == 1.1020
    assert current.low == 1.0990
    assert current.volume == 3


def test_candle_completion_handler_fires():
    builder = CandleBuilder(timeframes=["1m"])
    builder.register_symbol("frxEURUSD")
    completed = []
    builder.on_candle_complete(lambda c: completed.append(c))

    # First tick starts candle at epoch 1700000000
    builder.on_tick(make_tick(price=1.1000, epoch_s=1_700_000_000))
    # Tick in next minute finalizes the previous candle
    builder.on_tick(make_tick(price=1.1005, epoch_s=1_700_000_060))

    assert len(completed) == 1
    assert completed[0].open == 1.1000
    assert completed[0].close == 1.1000


def test_seed_history_only_when_empty():
    builder = CandleBuilder(timeframes=["15m"])
    builder.register_symbol("frxEURUSD")

    history = [
        Candle("frxEURUSD", "15m", 1.10, 1.11, 1.09, 1.105, 0, 1_700_000_000 + i * 900)
        for i in range(5)
    ]
    builder.seed_history("frxEURUSD", "15m", history)
    assert len(builder.get_candles("frxEURUSD", "15m")) == 5

    # Seeding again must not duplicate
    builder.seed_history("frxEURUSD", "15m", history)
    assert len(builder.get_candles("frxEURUSD", "15m")) == 5


def test_latest_price_tracks_ticks():
    builder = CandleBuilder(timeframes=["1m"])
    builder.register_symbol("frxEURUSD")
    builder.on_tick(make_tick(price=1.1000, epoch_s=1_700_000_000))
    builder.on_tick(make_tick(price=1.1010, epoch_s=1_700_000_005))
    assert builder.get_latest_price("frxEURUSD") == 1.1010


def test_session_awareness():
    builder = CandleBuilder()
    session = builder.is_session_active()
    assert {"london", "ny", "asian", "overlap_london_ny"} <= set(session.keys())
    assert "market_open" in session


def test_weekend_gate_closes_market_on_saturday(monkeypatch):
    # 2026-08-01 is a Saturday, 06:00 UTC (would otherwise be the Asian session)
    FakeDateTime.fixed = datetime(2026, 8, 1, 6, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("src.data_engine.candle_builder.datetime", FakeDateTime)

    session = CandleBuilder().is_session_active()
    assert session["market_open"] is False
    assert not any([session["london"], session["ny"], session["asian"]])


def test_weekend_gate_closes_market_sunday_before_open(monkeypatch):
    # Sunday 2026-08-02, 18:00 UTC (forex reopens 22:00 UTC)
    FakeDateTime.fixed = datetime(2026, 8, 2, 18, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("src.data_engine.candle_builder.datetime", FakeDateTime)

    session = CandleBuilder().is_session_active()
    assert session["market_open"] is False
    assert not any([session["london"], session["ny"], session["asian"]])


def test_weekend_gate_opens_sunday_night(monkeypatch):
    # Sunday 22:30 UTC: the new week has opened
    FakeDateTime.fixed = datetime(2026, 8, 2, 22, 30, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("src.data_engine.candle_builder.datetime", FakeDateTime)

    session = CandleBuilder().is_session_active()
    assert session["market_open"] is True
    # Hour 22 falls outside all session windows
    assert not any([session["london"], session["ny"], session["asian"]])


def test_weekend_gate_closes_friday_night(monkeypatch):
    # Friday 2026-07-31, 23:00 UTC: forex has closed
    FakeDateTime.fixed = datetime(2026, 7, 31, 23, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("src.data_engine.candle_builder.datetime", FakeDateTime)

    session = CandleBuilder().is_session_active()
    assert session["market_open"] is False


def test_weekend_gate_keeps_midweek_sessions(monkeypatch):
    # Wednesday 2026-07-29, 10:00 UTC (London session, NY not yet open)
    FakeDateTime.fixed = datetime(2026, 7, 29, 10, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("src.data_engine.candle_builder.datetime", FakeDateTime)

    session = CandleBuilder().is_session_active()
    assert session["market_open"] is True
    assert session["london"] is True
    assert session["ny"] is False


def test_weekend_gate_can_be_disabled(monkeypatch):
    # Saturday 06:00 UTC with the gate disabled behaves like the old logic
    FakeDateTime.fixed = datetime(2026, 8, 1, 6, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("src.data_engine.candle_builder.datetime", FakeDateTime)

    session = CandleBuilder().is_session_active(weekend_gate=False)
    assert session["market_open"] is True
    assert session["asian"] is True
