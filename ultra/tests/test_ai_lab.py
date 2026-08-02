"""
Tests for the AI Research Lab (Phase 16): MarketAdvisor + SignalEnhancer.
"""
import pytest

from src.ai_lab.advisor import MarketAdvisor
from src.ai_lab.signal_enhancer import SignalEnhancer
from src.strategies.ema_crossover import TradeSignal, SignalDirection, SignalStrength

from conftest import make_snapshot


def _signal(direction=SignalDirection.BUY, confidence=0.7):
    return TradeSignal(
        symbol="frxEURUSD",
        direction=direction,
        strength=SignalStrength.MODERATE,
        confidence=confidence,
        timestamp=pytest.importorskip("pandas").Timestamp("2026-01-01", tz="UTC"),
        entry_price=1.10,
        stop_loss=1.099,
        take_profit=1.102,
        strategy_name="EMACrossover",
        timeframe="15m",
        reason="EMA crossover bullish",
    )


# === MarketAdvisor ===


def test_advisor_bullish_alignment_recommends_buy():
    snap = make_snapshot(trend="bullish", macd_hist=0.0001, adx=35.0, rsi=55.0)
    rec = MarketAdvisor().advise(snap)
    assert rec.action == "trade_buy"
    assert rec.momentum == "bullish"
    assert rec.regime == "bullish"
    assert rec.confidence > 0.5


def test_advisor_bearish_alignment_recommends_sell():
    snap = make_snapshot(
        trend="bearish", macd_hist=-0.0001, adx=35.0, rsi=45.0,
        ema_fast=1.0980, ema_slow=1.0990, ema_trend=1.1000,
    )
    rec = MarketAdvisor().advise(snap)
    assert rec.action == "trade_sell"
    assert rec.momentum == "bearish"


def test_advisor_neutral_regime_observes():
    snap = make_snapshot(trend="neutral", macd_hist=0.0, adx=35.0, rsi=55.0)
    rec = MarketAdvisor().advise(snap)
    assert rec.action == "observe"


def test_advisor_trend_momentum_conflict_observes():
    snap = make_snapshot(trend="bullish", macd_hist=-0.0002, adx=35.0, rsi=55.0)
    rec = MarketAdvisor().advise(snap)
    assert rec.action == "observe"
    assert any("disagree" in r for r in rec.reasons)


def test_advisor_overbought_appetite_low():
    snap = make_snapshot(trend="bullish", macd_hist=0.0001, adx=35.0, rsi=80.0)
    rec = MarketAdvisor().advise(snap)
    assert rec.risk_appetite == "low"
    assert rec.action == "observe"


def test_advisor_weak_adx_flat_momentum():
    snap = make_snapshot(trend="bullish", macd_hist=0.0001, adx=10.0, rsi=55.0)
    rec = MarketAdvisor().advise(snap)
    assert rec.momentum == "flat"
    assert rec.action == "observe"


def test_advisor_to_dict():
    snap = make_snapshot(trend="bullish", macd_hist=0.0001, adx=35.0, rsi=55.0)
    d = MarketAdvisor().advise(snap).to_dict()
    assert d["action"] == "trade_buy"
    assert 0.0 <= d["confidence"] <= 1.0
    assert isinstance(d["reasons"], list) and d["reasons"]


# === SignalEnhancer ===


def test_enhancer_confirming_advisor_boosts_confidence():
    snap = make_snapshot(trend="bullish", macd_hist=0.0001, adx=35.0, rsi=55.0)
    signal = _signal(SignalDirection.BUY, confidence=0.7)
    enhanced = SignalEnhancer().enhance(signal, snap)
    assert enhanced.confidence > 0.7
    assert "advisor confirms" in enhanced.reason
    # Original untouched (deep copy).
    assert signal.confidence == 0.7


def test_enhancer_disagreeing_advisor_penalises():
    snap = make_snapshot(trend="bearish", macd_hist=-0.0001, adx=35.0, rsi=45.0,
                         ema_fast=1.0980, ema_slow=1.0990, ema_trend=1.1000)
    signal = _signal(SignalDirection.BUY, confidence=0.7)
    enhanced = SignalEnhancer().enhance(signal, snap)
    assert enhanced.confidence < 0.7
    assert "advisor disagrees" in enhanced.reason


def test_enhancer_higher_timeframe_confirms():
    snap = make_snapshot(trend="bullish", macd_hist=0.0001, adx=35.0, rsi=55.0)
    ht = make_snapshot(trend="bullish", macd_hist=0.0001, adx=35.0, rsi=55.0)
    signal = _signal(SignalDirection.BUY, confidence=0.6)
    enhanced = SignalEnhancer().enhance(signal, snap, higher_tf_snapshot=ht)
    assert enhanced.confidence > 0.6
    assert "higher-timeframe" in enhanced.reason


def test_enhancer_higher_timeframe_conflicts():
    # Neutral snapshot -> advisor neither confirms nor disagrees, so the
    # higher-timeframe conflict penalty is the only adjustment.
    snap = make_snapshot(trend="neutral", macd_hist=0.0, adx=10.0, rsi=55.0)
    ht = make_snapshot(trend="bearish", macd_hist=-0.0001, adx=35.0, rsi=45.0,
                       ema_fast=1.0980, ema_slow=1.0990, ema_trend=1.1000)
    signal = _signal(SignalDirection.BUY, confidence=0.8)
    enhanced = SignalEnhancer().enhance(signal, snap, higher_tf_snapshot=ht)
    assert enhanced.confidence == pytest.approx(0.75)
    assert "conflicts" in enhanced.reason


def test_enhancer_hold_is_unchanged():
    snap = make_snapshot(trend="bullish", macd_hist=0.0001, adx=35.0, rsi=55.0)
    signal = _signal(SignalDirection.HOLD, confidence=0.0)
    enhanced = SignalEnhancer().enhance(signal, snap)
    assert enhanced.direction == SignalDirection.HOLD
    assert enhanced.confidence == 0.0


def test_enhancer_strength_refreshes_from_confidence():
    snap = make_snapshot(trend="bullish", macd_hist=0.0001, adx=35.0, rsi=55.0)
    signal = _signal(SignalDirection.BUY, confidence=0.6)
    enhanced = SignalEnhancer().enhance(signal, snap)
    assert enhanced.strength in (SignalStrength.STRONG, SignalStrength.MODERATE)
