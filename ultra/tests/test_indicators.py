"""
Tests for Phase 4 — Indicator Engine.
"""
import numpy as np
import pandas as pd
import pytest

from src.indicators.technical import IndicatorEngine


def test_calculate_returns_snapshot(synthetic_candles):
    engine = IndicatorEngine()
    snap = engine.calculate(synthetic_candles, "frxEURUSD", "15m")

    assert snap is not None
    assert snap.symbol == "frxEURUSD"
    assert snap.ema_fast is not None
    assert snap.ema_slow is not None
    assert snap.ema_trend is not None
    assert 0 <= snap.rsi <= 100
    assert snap.atr > 0
    assert snap.macd_line is not None
    assert snap.bb_upper > snap.bb_lower
    assert snap.adx >= 0
    assert snap.trend_direction in ("bullish", "bearish", "neutral")


def test_insufficient_data_returns_none():
    engine = IndicatorEngine()
    small = pd.DataFrame({
        "open": [1.1, 1.1], "high": [1.1, 1.1],
        "low": [1.1, 1.1], "close": [1.1, 1.1],
    }, index=pd.date_range("2026-01-01", periods=2, freq="1h"))
    assert engine.calculate(small, "frxEURUSD", "15m") is None


def test_rsi_no_nan_on_flat_price():
    """Flat price (zero loss) must produce RSI=100, never NaN."""
    engine = IndicatorEngine()
    n = 250  # >= ema_trend (200) so calculate() returns a snapshot
    flat = pd.DataFrame({
        "open": [1.10] * n, "high": [1.10] * n,
        "low": [1.10] * n, "close": [1.10] * n,
        "volume": [0] * n,
    }, index=pd.date_range("2026-01-01", periods=n, freq="1h"))
    snap = engine.calculate(flat, "frxEURUSD", "1h")
    assert snap is not None
    assert snap.rsi is not None
    assert not np.isnan(snap.rsi)


def test_monotonic_uptrend_is_bullish(trending_candles):
    engine = IndicatorEngine(ema_fast=8, ema_slow=21, ema_trend=50)
    snap = engine.calculate(trending_candles, "frxEURUSD", "15m")
    assert snap.trend_direction == "bullish"
