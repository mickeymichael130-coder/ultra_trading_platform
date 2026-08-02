"""
Tests for Phase 10 — Analytics Engine.
"""
from datetime import datetime, timedelta

import pytest

from src.database.manager import DatabaseManager
from src.analytics.reports import AnalyticsEngine


@pytest.fixture
def db_with_trades(tmp_path):
    db = DatabaseManager(str(tmp_path / "test.db"))

    now = datetime.utcnow()
    trades = [
        {"exec_id": f"EXEC_{i}", "symbol": "frxEURUSD", "direction": "BUY",
         "strategy": "test", "timeframe": "15m", "entry_price": 1.10,
         "exit_price": 1.11, "realized_pnl": 10.0, "status": "closed",
         "mode": "paper", "closed_at": (now - timedelta(hours=i)).isoformat()}
        for i in range(10)
    ]
    for t in trades:
        db.save_trade(t)

    yield db
    db._get_connection().close()


def test_generate_report_metrics(db_with_trades):
    engine = AnalyticsEngine(db_with_trades)
    report = engine.generate_report(days=30)

    assert report.total_trades == 10
    assert report.winning_trades == 10
    assert report.win_rate == 100.0
    assert report.net_pnl == 100.0
    assert report.profit_factor > 1
    assert report.consecutive_wins == 10


def test_empty_report(db_with_trades):
    engine = AnalyticsEngine(db_with_trades)
    report = engine.generate_report(days=0)
    # days=0 excludes everything
    assert report.total_trades == 0


def test_report_to_dict(db_with_trades):
    engine = AnalyticsEngine(db_with_trades)
    report = engine.generate_report(days=30)
    data = report.to_dict()
    assert data["net_pnl"] == 100.0
    assert "consecutive_losses" in data
