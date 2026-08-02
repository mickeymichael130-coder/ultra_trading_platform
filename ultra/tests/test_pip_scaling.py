"""
Tests for crypto-aware pip scaling (iteration 7: Binance integration).

get_pip_size is now symbol-aware so ATR/stop-loss/pip-value math stays
consistent for Binance crypto pairs as well as Deriv forex.
"""
import numpy as np
import pandas as pd
import pytest

from src.utils.pips import get_pip_size, is_crypto_symbol
from src.indicators.technical import IndicatorEngine


# === is_crypto_symbol ===


@pytest.mark.parametrize("symbol,expected", [
    ("BTCUSDT", True),
    ("ETHUSDT", True),
    ("SOLUSDT", True),
    ("frxEURUSD", False),
    ("frxUSDJPY", False),
    ("EUR/USD", False),
    ("BTCUSDC", True),
    ("ETHBTC", True),
])
def test_is_crypto_symbol(symbol, expected):
    assert is_crypto_symbol(symbol) is expected


# === get_pip_size ===


@pytest.mark.parametrize("symbol,pip", [
    ("frxEURUSD", 0.0001),
    ("frxGBPUSD", 0.0001),
    ("frxUSDJPY", 0.01),
    ("BTCUSDT", 1.0),
    ("BTCUSDC", 1.0),
    ("ETHUSDT", 1.0),
    ("SOLUSDT", 0.01),
    ("XRPUSDT", 0.01),
    ("DOGEUSDT", 0.01),
])
def test_get_pip_size(symbol, pip):
    assert get_pip_size(symbol) == pip


# === IndicatorEngine atr_pips is symbol-aware ===


def _make_candles(close_base, vol_abs, n=300, freq="15min"):
    idx = pd.date_range("2026-01-01", periods=n, freq=freq, tz="UTC")
    close = close_base + np.random.default_rng(1).normal(0, vol_abs, n).cumsum()
    close = np.abs(close)
    return pd.DataFrame({
        "open": close,
        "high": close + vol_abs,
        "low": close - vol_abs,
        "close": close,
        "volume": np.full(n, 100.0),
    }, index=idx)


def test_indicator_calculate_uses_crypto_pip():
    df = _make_candles(close_base=50000.0, vol_abs=100.0)
    engine = IndicatorEngine()
    snap = engine.calculate(df, "BTCUSDT", "15m")

    assert snap is not None
    # BTC atr ~200 (pip=1.0) -> atr_pips ~200, not ~2,000,000 (0.0001 pip)
    assert 100 < snap.atr_pips < 500


def test_indicator_calculate_uses_forex_pip():
    df = _make_candles(close_base=1.10, vol_abs=0.001)
    engine = IndicatorEngine()
    snap = engine.calculate(df, "frxEURUSD", "15m")

    assert snap is not None
    # EURUSD atr ~0.002 (pip=0.0001) -> atr_pips ~20
    assert 10 < snap.atr_pips < 60


def test_indicator_calculate_series_symbol_aware():
    df = _make_candles(close_base=50000.0, vol_abs=100.0)
    engine = IndicatorEngine()

    series = engine.calculate_series(df, "BTCUSDT")
    last = series["atr_pips"].dropna().iloc[-1]
    assert 100 < last < 500

    # Without a symbol the configured forex default (0.0001) applies.
    series_default = engine.calculate_series(df)
    last_default = series_default["atr_pips"].dropna().iloc[-1]
    assert last_default > last * 1000
