"""
Shared pytest fixtures and helpers for ULTRA tests.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SRC = Path(__file__).parent.parent
sys.path.insert(0, str(SRC))


def make_snapshot(
    price=1.1000,
    ema_fast=1.1010,
    ema_slow=1.1000,
    ema_trend=1.0990,
    rsi=55.0,
    atr=0.0012,
    adx=30.0,
    trend="bullish",
    macd_hist=0.0001,
):
    """Build a fully-populated MarketSnapshot for strategy/risk tests."""
    from src.indicators.technical import MarketSnapshot

    return MarketSnapshot(
        symbol="frxEURUSD",
        timeframe="15m",
        timestamp=pd.Timestamp("2026-01-01", tz="UTC"),
        current_price=price,
        open=price, high=price + 0.0005, low=price - 0.0005, close=price,
        ema_fast=ema_fast, ema_slow=ema_slow, ema_trend=ema_trend,
        rsi=rsi, atr=atr, atr_pips=atr / 0.0001,
        macd_line=0.0001, macd_signal=0.00005, macd_histogram=macd_hist,
        bb_upper=price + 0.002, bb_middle=price, bb_lower=price - 0.002,
        adx=adx, adx_plus_di=25.0, adx_minus_di=15.0,
        volume=500, trend_direction=trend, volatility_regime="normal",
    )


@pytest.fixture
def synthetic_candles():
    """Synthetic trending OHLC dataset with a clear EMA crossover."""
    rng = np.random.default_rng(42)
    n = 600
    # U-shaped price so fast EMA crosses slow EMA both directions
    x = np.linspace(0, 1, n)
    trend = np.sin(x * 3 * np.pi) * 0.0015
    noise = rng.normal(0, 0.0002, n)
    close = 1.1000 + trend + np.cumsum(noise)
    close = np.abs(close)

    idx = pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC")
    df = pd.DataFrame({
        "open": close,
        "high": close + 0.0004,
        "low": close - 0.0004,
        "close": close,
        "volume": rng.integers(50, 500, n).astype(int)
    }, index=idx)

    return df


@pytest.fixture
def trending_candles():
    """Strong monotonic uptrend for deterministic bullish signals."""
    rng = np.random.default_rng(7)
    n = 400
    close = 1.1000 + np.linspace(0, 0.010, n) + rng.normal(0, 0.0001, n).cumsum() * 0.5
    idx = pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({
        "open": close,
        "high": close + 0.0005,
        "low": close - 0.0005,
        "close": close,
        "volume": rng.integers(100, 500, n).astype(int)
    }, index=idx)


@pytest.fixture
def crossover_candles():
    """
    Uptrend → pullback → rally, engineered to produce a real bullish EMA
    crossover during an established uptrend (so trades actually open).
    """
    rng = np.random.default_rng(3)
    n = 500
    pre = np.linspace(0, 0.004, 200) + rng.normal(0, 0.00005, 200).cumsum() * 0.3
    dip = 0.0006 * np.linspace(1, 0, 15)
    rally = np.linspace(0, 0.006, 285)
    close = np.concatenate([1.10 + pre, 1.1040 - dip, 1.1035 + rally])
    close = np.abs(close + rng.normal(0, 0.00008, n).cumsum() * 0.1)
    idx = pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({
        "open": close,
        "high": close + 0.0005,
        "low": close - 0.0005,
        "close": close,
        "volume": rng.integers(100, 600, n).astype(int)
    }, index=idx)
