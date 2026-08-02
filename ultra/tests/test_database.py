"""
Tests for Phase 9 — Database Layer.
"""
import os

import pandas as pd
import pytest

from src.database.manager import DatabaseManager


@pytest.fixture
def db(tmp_path):
    db = DatabaseManager(str(tmp_path / "test.db"))
    yield db
    db._get_connection().close()


def test_schema_tables_exist(db):
    conn = db._get_connection()
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    names = {t[0] for t in tables}
    assert {"candles", "trades", "balance", "risk_state",
            "signals", "performance", "system_logs"} <= names


def test_save_and_get_candles(db):
    idx = pd.date_range("2026-01-01", periods=3, freq="15min", tz="UTC")
    df = pd.DataFrame({
        "open": [1.10, 1.11, 1.12],
        "high": [1.11, 1.12, 1.13],
        "low": [1.09, 1.10, 1.11],
        "close": [1.105, 1.115, 1.125],
        "volume": [10, 20, 30],
    }, index=idx)
    db.save_candles(df, "frxEURUSD", "15m")

    out = db.get_candles("frxEURUSD", "15m", limit=10)
    assert len(out) == 3
    assert out["close"].min() == 1.105
    assert out["close"].max() == 1.125


def test_save_and_get_trades(db):
    db.save_trade({
        "exec_id": "EXEC_1", "symbol": "frxEURUSD", "direction": "BUY",
        "strategy": "test", "timeframe": "15m", "entry_price": 1.10,
        "status": "filled", "mode": "paper",
    })
    trades = db.get_trades()
    assert len(trades) == 1
    assert trades.iloc[0]["exec_id"] == "EXEC_1"


def test_update_trade(db):
    db.save_trade({
        "exec_id": "EXEC_1", "symbol": "frxEURUSD", "direction": "BUY",
        "strategy": "test", "timeframe": "15m", "status": "filled", "mode": "paper",
    })
    db.update_trade("EXEC_1", {"realized_pnl": 12.5, "status": "closed"})
    trades = db.get_trades()
    assert trades.iloc[0]["realized_pnl"] == 12.5
    assert trades.iloc[0]["status"] == "closed"


def test_risk_state_persistence(db):
    db.save_risk_state({
        "current_balance": 1900.0, "peak_balance": 2000.0,
        "daily_pnl": -100.0, "kill_switch_active": True,
    })
    state = db.load_risk_state()
    assert state["current_balance"] == 1900.0
    assert state["kill_switch_active"] is True


def test_balance_snapshot(db):
    db.save_balance(1990.0)
    db.save_balance(1980.0)
    assert db.get_latest_balance() == 1980.0


def test_signal_record(db):
    db.save_signal(
        {"symbol": "frxEURUSD", "direction": "BUY", "confidence": 0.8},
        risk_decision="APPROVE",
    )
    conn = db._get_connection()
    row = conn.execute("SELECT * FROM signals WHERE symbol='frxEURUSD'").fetchone()
    assert row["risk_decision"] == "APPROVE"
