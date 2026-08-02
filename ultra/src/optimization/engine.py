"""
Optimization Engine
Grid-search parameter optimization for the trading strategy.
Wraps BacktestEngine.optimize() with a reusable public API.
"""
from typing import Dict, List, Optional
import pandas as pd

from ..backtesting.engine import BacktestEngine
from ..utils.logger import get_logger


class OptimizationEngine:
    """
    Parameter optimization for strategies.

    Runs the same strategy used in live trading across a parameter grid and
    returns combinations ranked by net P&L. Supports both indicator
    parameters (EMA periods, RSI period, etc.) and strategy parameters.
    """

    def __init__(self, initial_capital: float = 2000.0):
        self.initial_capital = initial_capital
        self.logger = get_logger("optimization.engine")
        self._backtest_engine = BacktestEngine(initial_capital=initial_capital)

    def optimize(
        self,
        candles_df: pd.DataFrame,
        symbol: str,
        param_grid: Dict[str, List],
        metric: str = "net_pnl"
    ) -> List[Dict]:
        """
        Run grid search over parameter combinations.

        Args:
            candles_df: OHLC DataFrame (open, high, low, close, volume)
            symbol: Trading symbol
            param_grid: Dict of parameter name -> list of candidate values
            metric: Sort metric (net_pnl, win_rate, profit_factor)

        Returns:
            Ranked list of results sorted by the chosen metric
        """
        results = self._backtest_engine.optimize(candles_df, symbol, param_grid)

        if not results:
            return results

        valid_metrics = {"net_pnl", "win_rate", "profit_factor", "max_drawdown", "total_trades"}
        if metric not in valid_metrics:
            self.logger.warning(f"Unknown metric '{metric}', defaulting to net_pnl")
            metric = "net_pnl"

        results.sort(key=lambda x: x[metric], reverse=True)

        self.logger.info(f"Optimization complete: {len(results)} combinations evaluated")
        return results

    def best(self, results: List[Dict]) -> Optional[Dict]:
        """Return the best result (already sorted, returns first)."""
        return results[0] if results else None
