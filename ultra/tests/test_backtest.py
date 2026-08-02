"""
Tests for Phase 11 (Backtesting) and Phase 12 (Optimization).
"""
import pytest

from src.backtesting.engine import BacktestEngine
from src.optimization.engine import OptimizationEngine


def test_backtest_runs_end_to_end(synthetic_candles):
    engine = BacktestEngine(initial_capital=2000.0)
    result = engine.run(synthetic_candles, symbol="frxEURUSD", timeframe="15m")

    assert result.total_trades >= 0
    assert result.win_rate >= 0
    assert 0 <= result.max_drawdown_pct < 100
    assert result.profit_factor >= 0
    assert len(result.equity_curve) == len(result.equity_times)


def test_backtest_metrics_consistent(synthetic_candles):
    engine = BacktestEngine(initial_capital=2000.0)
    result = engine.run(synthetic_candles, symbol="frxEURUSD", timeframe="15m")

    if result.total_trades > 0:
        assert result.winning_trades + result.losing_trades == result.total_trades
        assert abs(result.gross_profit - result.gross_loss - result.net_pnl) < 0.01


def test_backtest_opens_and_closes_trades(crossover_candles):
    """A real bullish crossover must open a trade and P&L must be sane."""
    engine = BacktestEngine(initial_capital=2000.0)
    result = engine.run(crossover_candles, symbol="frxEURUSD", timeframe="15m")

    assert result.total_trades >= 1
    # P&L per trade is bounded by realistic pip movement * micro-lot risk
    for trade in result.trades:
        assert abs(trade.pnl) < 100.0, f"Unrealistic P&L: {trade.pnl}"


def test_optimization_ranks_results(synthetic_candles):
    engine = BacktestEngine(initial_capital=2000.0)
    results = engine.optimize(
        synthetic_candles,
        symbol="frxEURUSD",
        param_grid={
            "ema_fast": [8, 12],
            "ema_slow": [21, 26],
        },
    )

    assert len(results) == 4
    assert results[0]["net_pnl"] >= results[-1]["net_pnl"]
    assert {"params", "net_pnl", "win_rate", "profit_factor", "total_trades"} <= set(results[0])


def test_optimization_engine_wrapper(synthetic_candles):
    engine = OptimizationEngine(initial_capital=2000.0)
    results = engine.optimize(
        synthetic_candles,
        symbol="frxEURUSD",
        param_grid={"min_atr_pips": [4.0, 6.0]},
        metric="net_pnl",
    )
    assert results
    assert engine.best(results) is not None
