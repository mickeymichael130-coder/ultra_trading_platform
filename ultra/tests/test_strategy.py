"""
Tests for Phase 5 — Strategy Engine (EMA Crossover + RSI).
"""
import pandas as pd
import pytest

from conftest import make_snapshot
from src.strategies.ema_crossover import EMACrossoverStrategy, SignalDirection


SESSION = {"london": True, "ny": True, "asian": False, "overlap_london_ny": False}


def test_bullish_crossover_generates_buy():
    strategy = EMACrossoverStrategy()
    prev = make_snapshot(ema_fast=1.0995, ema_slow=1.1000, trend="neutral")
    curr = make_snapshot(ema_fast=1.1005, ema_slow=1.1000, trend="bullish")

    signal = strategy.generate_signal(curr, SESSION, prev)
    assert signal.direction == SignalDirection.BUY
    assert signal.confidence >= 0.6
    assert signal.stop_loss < signal.entry_price
    assert signal.take_profit > signal.entry_price


def test_bearish_crossover_generates_sell():
    strategy = EMACrossoverStrategy()
    prev = make_snapshot(ema_fast=1.1005, ema_slow=1.1000, trend="bullish")
    curr = make_snapshot(
        ema_fast=1.0995, ema_slow=1.1000, ema_trend=1.1010,
        rsi=45.0, trend="bearish", macd_hist=-0.0001,
    )

    signal = strategy.generate_signal(curr, SESSION, prev)
    assert signal.direction == SignalDirection.SELL
    assert signal.stop_loss > signal.entry_price
    assert signal.take_profit < signal.entry_price


def test_no_crossover_returns_hold():
    strategy = EMACrossoverStrategy()
    prev = make_snapshot(ema_fast=1.1010, ema_slow=1.1000)
    curr = make_snapshot(ema_fast=1.1010, ema_slow=1.1000)
    signal = strategy.generate_signal(curr, SESSION, prev)
    assert signal.direction == SignalDirection.HOLD


def test_low_atr_blocks_signal():
    strategy = EMACrossoverStrategy(min_atr_pips=5.0)
    prev = make_snapshot(ema_fast=1.0995, ema_slow=1.1000, trend="neutral")
    # atr=0.0001 → atr_pips = 1.0, below the 5.0 minimum
    curr = make_snapshot(ema_fast=1.1005, ema_slow=1.1000, atr=0.0001)
    signal = strategy.generate_signal(curr, SESSION, prev)
    assert signal.direction == SignalDirection.HOLD


def test_rsi_overbought_blocks_buy():
    strategy = EMACrossoverStrategy(rsi_overbought=70.0)
    prev = make_snapshot(ema_fast=1.0995, ema_slow=1.1000, trend="neutral")
    curr = make_snapshot(ema_fast=1.1005, ema_slow=1.1000, rsi=85.0)
    signal = strategy.generate_signal(curr, SESSION, prev)
    assert signal.direction == SignalDirection.HOLD


def test_asian_session_blocks_signals():
    strategy = EMACrossoverStrategy(trade_asian=False)
    prev = make_snapshot(ema_fast=1.0995, ema_slow=1.1000, trend="neutral")
    curr = make_snapshot(ema_fast=1.1005, ema_slow=1.1000)
    session = {"london": False, "ny": False, "asian": True, "overlap_london_ny": False}
    signal = strategy.generate_signal(curr, session, prev)
    assert signal.direction == SignalDirection.HOLD
