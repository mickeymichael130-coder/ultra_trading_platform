"""
Smoke tests for the ULTRA Streamlit dashboard (Phase 13).

Uses streamlit.testing.v1.AppTest to run the real app script headlessly
against a temp SQLite database, verifying every page renders without
raising an exception.
"""
import sqlite3
from datetime import datetime

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest

from src.database.manager import DatabaseManager

APP_PATH = "src/dashboard/app.py"


def _populate(db_path: str):
    conn = sqlite3.connect(db_path)
    now = datetime.utcnow().isoformat(sep=" ")
    today = datetime.utcnow().date().isoformat()

    conn.execute("INSERT INTO balance (balance, equity, margin_used, free_margin) "
                 "VALUES (10000.0, 10000.0, 0.0, 10000.0)")
    conn.execute("INSERT OR REPLACE INTO risk_state (id, current_balance, peak_balance, daily_pnl, "
                 "daily_trades, kill_switch_active, today_date) "
                 "VALUES (1, 10120.0, 10500.0, 120.0, 3, 0, ?)", (today,))

    base = 1720000000
    for i in range(5):
        conn.execute(
            "INSERT INTO candles (symbol, timeframe, epoch, open, high, low, close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("frxEURUSD", "15m", base + i * 900,
             1.1000 + i * 0.0001, 1.1010 + i * 0.0001, 1.0990 + i * 0.0001,
             1.1005 + i * 0.0001, 100 + i))

    conn.execute(
        "INSERT INTO trades (exec_id, symbol, direction, strategy, timeframe, entry_price, "
        "exit_price, stop_loss, take_profit, position_size, risk_amount, realized_pnl, "
        "status, mode, opened_at, closed_at, exit_reason, confidence) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("open-1", "frxEURUSD", "BUY", "EMACrossover", "15m", 1.1000, None, 1.0980, 1.1040,
         2.0, 20.0, None, "open", "paper", now, None, None, 0.75))
    conn.execute(
        "INSERT INTO trades (exec_id, symbol, direction, strategy, timeframe, entry_price, "
        "exit_price, stop_loss, take_profit, position_size, risk_amount, realized_pnl, "
        "status, mode, opened_at, closed_at, exit_reason, confidence) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("win-1", "frxEURUSD", "BUY", "EMACrossover", "15m", 1.1000, 1.1040, 1.0980, 1.1060,
         2.0, 20.0, 80.0, "closed", "paper", now, now, "take_profit", 0.8))
    conn.execute(
        "INSERT INTO trades (exec_id, symbol, direction, strategy, timeframe, entry_price, "
        "exit_price, stop_loss, take_profit, position_size, risk_amount, realized_pnl, "
        "status, mode, opened_at, closed_at, exit_reason, confidence) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("loss-1", "frxEURUSD", "BUY", "EMACrossover", "15m", 1.1000, 1.0980, 1.0975, 1.1060,
         2.0, 20.0, -40.0, "closed", "paper", now, now, "stop_loss", 0.6))

    conn.execute(
        "INSERT INTO signals (symbol, direction, strength, confidence, timestamp, strategy, "
        "timeframe, reason, risk_decision, risk_reason) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("frxEURUSD", "BUY", "strong", 0.75, now, "EMACrossover", "15m",
         "EMA cross", "accepted", "all checks passed"))
    conn.execute(
        "INSERT INTO performance (date, total_trades, winning_trades, losing_trades, "
        "win_rate, gross_profit, gross_loss, net_pnl, profit_factor) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (today, 2, 1, 1, 50.0, 80.0, 40.0, 40.0, 2.0))

    conn.commit()
    conn.close()


def _run_app(db_path: str):
    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.run()
    at.sidebar.text_input[0].set_value(db_path)
    at.run()
    return at


def test_dashboard_renders_without_db(tmp_path):
    """Missing DB file must not crash the app."""
    at = _run_app(str(tmp_path / "nonexistent.db"))
    assert not at.exception


def test_dashboard_renders_empty_db(tmp_path):
    """Fresh empty DB (schema only) must render every page."""
    db_path = str(tmp_path / "empty.db")
    DatabaseManager(db_path)
    at = _run_app(db_path)
    assert not at.exception


def test_dashboard_renders_with_data(tmp_path):
    """Populated DB must render every page and show metrics."""
    db_path = str(tmp_path / "filled.db")
    DatabaseManager(db_path)
    _populate(db_path)

    at = _run_app(db_path)
    assert not at.exception
    assert at.sidebar.text_input[0].value == db_path


def test_dashboard_all_pages_navigate(tmp_path):
    """Switching to every sidebar page must not raise."""
    db_path = str(tmp_path / "nav.db")
    DatabaseManager(db_path)
    _populate(db_path)

    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.run()
    at.sidebar.text_input[0].set_value(db_path)
    at.run()

    radio = at.sidebar.radio[0]
    for i in range(len(radio.options)):
        radio.set_value(radio.options[i])
        at.run()
        assert not at.exception


def test_dashboard_signals_shows_ai_notes(tmp_path):
    """Signals page must surface the persisted AI research notes."""
    db_path = str(tmp_path / "signals.db")
    DatabaseManager(db_path)
    _populate(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO signals (symbol, direction, strength, confidence, timestamp, strategy, "
        "timeframe, reason, risk_decision, risk_reason) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("frxGBPUSD", "SELL", "strong", 0.88, datetime.utcnow().isoformat(sep=" "),
         "EMACrossover", "15m",
         "AI: bearish regime on H1; momentum fading; risk appetite low; confidence boosted",
         "rejected", "max open trades reached"))
    conn.commit()
    conn.close()

    at = AppTest.from_file(APP_PATH, default_timeout=60)
    at.run()
    at.sidebar.text_input[0].set_value(db_path)
    at.run()

    at.sidebar.radio[0].set_value("🔔 Signals")
    at.run()
    assert not at.exception

    # AI notes are rendered as expanders
    assert len(at.expander) >= 1
    note_texts = [m.value for e in at.expander for m in e.markdown]
    assert any("AI: bearish regime" in t for t in note_texts)

    # The full history table also carries the reason column
    df = at.dataframe[0].value
    assert "reason" in df.columns
    assert df["reason"].astype(str).str.contains("AI:").any()
