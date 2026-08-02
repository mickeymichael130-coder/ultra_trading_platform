"""
Tests for Phase 6 — Risk Engine (the gatekeeper).
"""
import pandas as pd
import pytest

from conftest import make_snapshot
from src.strategies.ema_crossover import TradeSignal, SignalDirection, SignalStrength
from src.risk.manager import RiskManager, RiskDecision


def make_signal(direction=SignalDirection.BUY, entry=1.1000, sl=1.0985, tp=1.1040, confidence=0.8):
    return TradeSignal(
        symbol="frxEURUSD",
        direction=direction,
        strength=SignalStrength.MODERATE,
        confidence=confidence,
        timestamp=pd.Timestamp("2026-01-01", tz="UTC"),
        entry_price=entry,
        stop_loss=sl,
        take_profit=tp,
        atr=0.0012,
        strategy_name="test",
        timeframe="15m",
    )


def test_approves_valid_signal():
    rm = RiskManager(initial_capital=2000.0)
    result = rm.evaluate(make_signal(), 2000.0)
    assert result.is_approved
    assert result.modified_signal is not None
    assert result.modified_signal.risk_amount <= rm.max_risk_per_trade_abs


def test_rejects_when_kill_switch_active():
    rm = RiskManager(initial_capital=2000.0)
    rm._kill_switch_active = True
    result = rm.evaluate(make_signal(), 2000.0)
    assert result.decision == RiskDecision.REJECT
    assert "kill" in result.reason.lower()


def test_activates_kill_switch_on_drawdown():
    rm = RiskManager(initial_capital=2000.0)
    rm._peak_balance = 2000.0
    rm._current_balance = 1800.0  # 10% drawdown → kill switch
    result = rm.evaluate(make_signal(), 1800.0)
    assert rm._kill_switch_active
    assert not result.is_approved


def test_rejects_on_daily_loss_limit():
    rm = RiskManager(initial_capital=2000.0)
    rm._daily_pnl = -61.0  # > $60 limit
    result = rm.evaluate(make_signal(), 2000.0)
    assert result.decision == RiskDecision.REJECT
    assert "daily loss" in result.reason.lower()


def test_rejects_over_max_open_trades():
    rm = RiskManager(initial_capital=2000.0)
    rm.on_trade_opened({"id": "1", "symbol": "frxGBPUSD", "direction": "BUY", "risk_amount": 30})
    rm.on_trade_opened({"id": "2", "symbol": "frxAUDUSD", "direction": "SELL", "risk_amount": 30})
    result = rm.evaluate(make_signal(), 2000.0)
    assert result.decision == RiskDecision.REJECT


def test_cooldown_after_loss():
    from datetime import datetime, timedelta
    rm = RiskManager(initial_capital=2000.0)
    rm._last_loss_time = datetime.utcnow() - timedelta(minutes=5)
    result = rm.evaluate(make_signal(), 2000.0)
    assert result.decision == RiskDecision.COOLDOWN


def test_cooldown_expired_allows_trade():
    from datetime import datetime, timedelta
    rm = RiskManager(initial_capital=2000.0)
    rm._last_loss_time = datetime.utcnow() - timedelta(minutes=30)
    result = rm.evaluate(make_signal(), 2000.0)
    assert result.is_approved


def test_rejects_low_confidence():
    rm = RiskManager(initial_capital=2000.0)
    result = rm.evaluate(make_signal(confidence=0.3), 2000.0)
    assert result.decision == RiskDecision.REJECT
    assert "confidence" in result.reason.lower()


def test_rejects_correlated_pairs():
    rm = RiskManager(initial_capital=2000.0)
    rm.on_trade_opened({"id": "1", "symbol": "frxEURUSD", "direction": "BUY", "risk_amount": 30})
    # GBPUSD is in the same correlation group as EURUSD
    sig = make_signal()
    sig.symbol = "frxGBPUSD"
    result = rm.evaluate(sig, 2000.0)
    assert result.decision == RiskDecision.REJECT


def test_position_size_respects_max_risk():
    rm = RiskManager(initial_capital=2000.0, max_risk_per_trade_abs=30.0)
    result = rm.evaluate(make_signal(), 2000.0)
    assert result.modified_signal.risk_amount <= 30.0
