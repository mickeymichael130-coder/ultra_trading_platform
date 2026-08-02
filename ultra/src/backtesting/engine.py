"""
ULTRA Backtesting Engine
Feeds historical candles through the same strategy used in live trading.
Everything else stays exactly the same.
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass, field

from ..indicators.technical import IndicatorEngine, MarketSnapshot
from ..strategies.ema_crossover import EMACrossoverStrategy, TradeSignal, SignalDirection
from ..risk.manager import RiskManager, RiskResult, RiskDecision
from ..utils.logger import get_logger
from ..utils.pips import get_pip_size


@dataclass
class BacktestTrade:
    """Simulated trade result"""
    entry_time: datetime
    exit_time: Optional[datetime] = None
    symbol: str = ""
    direction: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    position_size: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""
    confidence: float = 0.0


@dataclass
class BacktestResult:
    """Complete backtest results"""
    trades: List[BacktestTrade] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    equity_times: List[datetime] = field(default_factory=list)

    # Metrics
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    net_pnl: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    sharpe_ratio: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": round(self.win_rate, 2),
            "net_pnl": round(self.net_pnl, 2),
            "profit_factor": round(self.profit_factor, 2),
            "max_drawdown": round(self.max_drawdown, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "avg_win": round(self.avg_win, 2),
            "avg_loss": round(self.avg_loss, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 2)
        }


class BacktestEngine:
    """
    Backtesting Engine.

    Instead of live ticks, feeds historical candles through:
    Indicator Engine → Strategy Engine → Risk Engine → Virtual Execution

    Uses the EXACT same code as live trading for validation.
    """

    def __init__(
        self,
        initial_capital: float = 2000.0,
        commission_per_trade: float = 0.0,  # Deriv has no commission on forex CFDs
        slippage_pips: float = 0.5
    ):
        self.initial_capital = initial_capital
        self.commission = commission_per_trade
        self.slippage_pips = slippage_pips

        self.logger = get_logger("backtest.engine")

        # Components (same as live)
        self.indicator_engine = IndicatorEngine()
        self.strategy = EMACrossoverStrategy()
        self.risk_manager = RiskManager(initial_capital=initial_capital)

        self.logger.info(f"BacktestEngine initialized | Capital: ${initial_capital}")

    def run(
        self,
        candles_df: pd.DataFrame,
        symbol: str,
        timeframe: str = "15m"
    ) -> BacktestResult:
        """
        Run backtest on historical candle data.

        Args:
            candles_df: DataFrame with columns [open, high, low, close, volume]
            symbol: Trading symbol
            timeframe: Candle timeframe

        Returns:
            BacktestResult with full statistics
        """
        self.logger.info(f"Starting backtest: {symbol} | {timeframe} | {len(candles_df)} candles")

        result = BacktestResult()
        equity = self.initial_capital
        result.equity_curve.append(equity)
        result.equity_times.append(candles_df.index[0] if hasattr(candles_df.index[0], 'to_pydatetime') else datetime.utcnow())

        peak_equity = equity
        max_dd = 0.0

        # Track state
        last_snapshot: Optional[MarketSnapshot] = None
        active_trade: Optional[BacktestTrade] = None

        # Precompute indicator series ONCE (indicators only use past data, so
        # this is identical to incremental computation but far faster).
        indicator_series = self.indicator_engine.calculate_series(candles_df, symbol)

        # Walk forward candle by candle
        for i in range(200, len(candles_df)):
            current_time = candles_df.index[i]
            current_candle = candles_df.iloc[i]

            # Build snapshot from precomputed indicators
            row = indicator_series.iloc[i]
            if pd.isna(row.get("ema_trend")) or pd.isna(row.get("atr")):
                continue
            snapshot = self.indicator_engine.snapshot_from_row(row, symbol, timeframe)

            # Check active trade for exit
            if active_trade:
                exit_triggered, exit_price, exit_reason = self._check_exit(
                    active_trade, current_candle, snapshot
                )

                if exit_triggered:
                    # Close trade
                    active_trade.exit_time = current_time
                    active_trade.exit_price = exit_price
                    active_trade.pnl = self._calculate_pnl(active_trade)
                    active_trade.exit_reason = exit_reason

                    equity += active_trade.pnl
                    result.trades.append(active_trade)

                    # Update risk manager
                    self.risk_manager.on_trade_closed(
                        {'id': len(result.trades), 'symbol': symbol},
                        active_trade.pnl
                    )

                    # Track drawdown
                    if equity > peak_equity:
                        peak_equity = equity
                    dd = peak_equity - equity
                    if dd > max_dd:
                        max_dd = dd

                    result.equity_curve.append(equity)
                    result.equity_times.append(current_time)

                    active_trade = None

                    # Update risk state
                    self.risk_manager._current_balance = equity
                    continue

            # Generate signal (only if no active trade)
            if not active_trade:
                session_info = {"london": True, "ny": True, "asian": False, "overlap_london_ny": True}
                signal = self.strategy.generate_signal(snapshot, session_info, last_snapshot)

                if signal.direction != SignalDirection.HOLD:
                    # Risk check
                    risk_result = self.risk_manager.evaluate(signal, equity)

                    if risk_result.is_approved:
                        # Simulate execution with slippage
                        modified = risk_result.modified_signal or signal
                        entry_price = self._apply_slippage(
                            modified.entry_price,
                            modified.direction.value,
                            symbol,
                            is_entry=True
                        )

                        active_trade = BacktestTrade(
                            entry_time=current_time,
                            symbol=symbol,
                            direction=modified.direction.value,
                            entry_price=entry_price,
                            stop_loss=modified.stop_loss or entry_price * 0.99,
                            take_profit=modified.take_profit or entry_price * 1.01,
                            position_size=modified.position_size or 0.01,
                            confidence=modified.confidence
                        )

                        # Update risk
                        self.risk_manager.on_trade_opened({
                            'id': len(result.trades),
                            'symbol': symbol,
                            'direction': modified.direction.value
                        })

            last_snapshot = snapshot

        # Close any remaining open trade at last price
        if active_trade:
            active_trade.exit_time = candles_df.index[-1]
            active_trade.exit_price = candles_df.iloc[-1]['close']
            active_trade.pnl = self._calculate_pnl(active_trade)
            active_trade.exit_reason = "end_of_data"
            equity += active_trade.pnl
            result.trades.append(active_trade)
            result.equity_curve.append(equity)
            result.equity_times.append(candles_df.index[-1])

        # Calculate metrics
        self._calculate_metrics(result, equity, max_dd, peak_equity)

        self.logger.info(f"Backtest complete: {result.total_trades} trades | P&L: ${result.net_pnl:.2f}")

        return result

    def _check_exit(
        self,
        trade: BacktestTrade,
        candle: pd.Series,
        snapshot: MarketSnapshot
    ) -> tuple:
        """Check if trade should be closed"""
        high = candle['high']
        low = candle['low']

        # Stop Loss
        if trade.direction == "BUY":
            if low <= trade.stop_loss:
                return True, trade.stop_loss, "stop_loss"
            if high >= trade.take_profit:
                return True, trade.take_profit, "take_profit"
        else:  # SELL
            if high >= trade.stop_loss:
                return True, trade.stop_loss, "stop_loss"
            if low <= trade.take_profit:
                return True, trade.take_profit, "take_profit"

        # Time exit (2 hours for intraday)
        elapsed = (snapshot.timestamp - trade.entry_time).total_seconds() / 3600
        if elapsed >= 2:
            return True, candle['close'], "time_exit"

        return False, 0.0, ""

    def _calculate_pnl(self, trade: BacktestTrade) -> float:
        """Calculate trade P&L based on pip movement and micro-lot size."""
        from ..utils.pips import pnl_from_price_move

        return pnl_from_price_move(
            trade.symbol, trade.direction,
            trade.entry_price, trade.exit_price,
            trade.position_size
        ) - self.commission

    def _apply_slippage(self, price: float, direction: str, symbol: str, is_entry: bool = True) -> float:
        """Apply slippage to price"""
        pip_size = get_pip_size(symbol)
        slippage = self.slippage_pips * pip_size

        if is_entry:
            if direction == "BUY":
                return price + slippage
            else:
                return price - slippage
        else:
            if direction == "BUY":
                return price - slippage
            else:
                return price + slippage

    def _calculate_metrics(self, result: BacktestResult, final_equity: float, max_dd: float, peak: float):
        """Calculate all performance metrics"""
        trades = result.trades
        result.total_trades = len(trades)

        if result.total_trades == 0:
            return

        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]

        result.winning_trades = len(wins)
        result.losing_trades = len(losses)
        result.win_rate = (len(wins) / len(trades)) * 100 if trades else 0

        result.gross_profit = sum(t.pnl for t in wins)
        result.gross_loss = abs(sum(t.pnl for t in losses))
        result.net_pnl = final_equity - self.initial_capital

        result.profit_factor = (
            result.gross_profit / result.gross_loss 
            if result.gross_loss > 0 else float('inf')
        )

        result.max_drawdown = max_dd
        result.max_drawdown_pct = (max_dd / peak * 100) if peak > 0 else 0

        result.avg_win = np.mean([t.pnl for t in wins]) if wins else 0
        result.avg_loss = np.mean([t.pnl for t in losses]) if losses else 0
        result.largest_win = max([t.pnl for t in wins]) if wins else 0
        result.largest_loss = min([t.pnl for t in losses]) if losses else 0

        # Sharpe ratio (simplified)
        returns = []
        for i in range(1, len(result.equity_curve)):
            if result.equity_curve[i-1] > 0:
                ret = (result.equity_curve[i] - result.equity_curve[i-1]) / result.equity_curve[i-1]
                returns.append(ret)

        if returns:
            mean_ret = np.mean(returns)
            std_ret = np.std(returns)
            result.sharpe_ratio = (mean_ret / std_ret * np.sqrt(252)) if std_ret > 0 else 0

    def optimize(
        self,
        candles_df: pd.DataFrame,
        symbol: str,
        param_grid: Dict[str, List]
    ) -> List[Dict]:
        """
        Grid search optimization.

        Supports both strategy parameters (min_atr_pips, min_confidence,
        rsi_overbought, rsi_oversold, adx_threshold) and indicator
        parameters (ema_fast, ema_slow, ema_trend, rsi_period, atr_period).
        A fresh IndicatorEngine + strategy is built for every combination.

        Args:
            param_grid: Dict of parameter names to lists of values
            Example: {"ema_fast": [8, 12, 16], "ema_slow": [21, 26, 30]}

        Returns:
            List of results sorted by net P&L
        """
        from itertools import product
        from ..indicators.technical import IndicatorEngine

        self.logger.info(f"Starting optimization: {len(param_grid)} parameters")

        keys = list(param_grid.keys())
        values = list(param_grid.values())

        indicator_params = {
            "ema_fast", "ema_slow", "ema_trend", "rsi_period",
            "atr_period", "macd_fast", "macd_slow", "macd_signal",
            "bb_period", "bb_std", "adx_period"
        }
        strategy_params = {
            "min_atr_pips", "min_confidence", "rsi_overbought",
            "rsi_oversold", "adx_threshold", "trade_london",
            "trade_ny", "trade_asian"
        }

        # Snapshot defaults for restoration after the run
        default_indicator = self.indicator_engine
        default_strategy = self.strategy

        results = []

        for combo in product(*values):
            params = dict(zip(keys, combo))

            # Build fresh engines for this combination
            ind_kwargs = {k: v for k, v in params.items() if k in indicator_params}
            strat_kwargs = {k: v for k, v in params.items() if k in strategy_params}

            self.indicator_engine = IndicatorEngine(**ind_kwargs)
            self.strategy = EMACrossoverStrategy(**strat_kwargs)

            # Run backtest
            try:
                result = self.run(candles_df, symbol)
            except Exception as e:
                self.logger.warning(f"Optimization combo failed {params}: {e}")
                continue

            results.append({
                "params": params,
                "net_pnl": round(result.net_pnl, 2),
                "win_rate": round(result.win_rate, 2),
                "profit_factor": round(result.profit_factor, 2),
                "max_drawdown": round(result.max_drawdown_pct, 2),
                "total_trades": result.total_trades
            })

        # Restore defaults
        self.indicator_engine = default_indicator
        self.strategy = default_strategy

        # Sort by net P&L
        results.sort(key=lambda x: x['net_pnl'], reverse=True)

        if results:
            self.logger.info(f"Optimization complete. Best P&L: ${results[0]['net_pnl']:.2f}")

        return results
