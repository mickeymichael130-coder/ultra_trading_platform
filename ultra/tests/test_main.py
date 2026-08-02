"""
Tests for main.py entry-point helpers (Phase 17 operations).
"""
from pathlib import Path

import main


def test_write_pid_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pid_file = main.write_pid_file()
    assert pid_file.exists()
    assert int(pid_file.read_text().strip()) > 0


def test_remove_pid_file(tmp_path):
    pid_file = tmp_path / "bot.pid"
    pid_file.write_text("12345")
    main.remove_pid_file(pid_file)
    assert not pid_file.exists()


def test_remove_pid_file_missing_is_noop(tmp_path):
    pid_file = tmp_path / "nope.pid"
    main.remove_pid_file(pid_file)
    assert not pid_file.exists()


def test_parse_args_defaults(monkeypatch):
    monkeypatch.delenv("TRADING_MODE", raising=False)
    args = main.parse_args([])
    assert args.mode == "paper"
    assert args.db == "data/ultra.db"
    assert args.timeframe == "15m"
    assert args.count == 2000


def test_parse_args_mode_override():
    args = main.parse_args(["--mode", "backtest", "--count", "500"])
    assert args.mode == "backtest"
    assert args.count == 500


def test_parse_args_broker_default_and_override(monkeypatch):
    monkeypatch.delenv("BROKER", raising=False)
    args = main.parse_args([])
    assert args.broker == "deriv"

    args = main.parse_args(["--broker", "binance"])
    assert args.broker == "binance"
