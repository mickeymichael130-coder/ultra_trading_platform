"""
ULTRA Analytics Engine
Produces performance reports from database.
Win rate, profit factor, drawdown, equity curve, monthly/daily profit.
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass

from ..database.manager import DatabaseManager
from ..utils.logger import get_logger


@dataclass
class PerformanceReport:
    """Complete performance report"""
    period: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    gross_profit: float
    gross_loss: float
    net_pnl: float
    profit_factor: float
    max_drawdown: float
    max_drawdown_pct: float
    avg_win: float
    avg_loss: float
    largest_win: float
    largest_loss: float
    avg_trade: float
    expectancy: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    consecutive_wins: int
    consecutive_losses: int

    def to_dict(self) -> Dict:
        return {k: round(v, 4) if isinstance(v, float) else v for k, v in self.__dict__.items()}


class AnalyticsEngine:
    """
    Analytics and Reporting Engine.

    Reads from database, produces:
    - Performance reports (daily, weekly, monthly)
    - Equity curves
    - Trade journals
    - Drawdown analysis
    - Consecutive win/loss streaks
    """

    def __init__(self, db: DatabaseManager):
        self.db = db
        self.logger = get_logger("analytics.engine")
        self.logger.info("AnalyticsEngine initialized")

    def generate_report(self, days: int = 30) -> PerformanceReport:
        """Generate performance report for last N days"""

        since = datetime.utcnow() - timedelta(days=days)

        # Get trades
        trades_df = self.db.get_trades(limit=1000)
        if trades_df.empty:
            self.logger.warning("No trades found for report generation")
            return self._empty_report(f"Last {days} days")

        # Filter by date
        if 'closed_at' in trades_df.columns:
            trades_df['closed_at'] = pd.to_datetime(trades_df['closed_at'])
            trades_df = trades_df[trades_df['closed_at'] >= since]

        # Calculate metrics
        closed_trades = trades_df[trades_df['realized_pnl'].notna()]

        if closed_trades.empty:
            return self._empty_report(f"Last {days} days")

        total = len(closed_trades)
        wins = closed_trades[closed_trades['realized_pnl'] > 0]
        losses = closed_trades[closed_trades['realized_pnl'] <= 0]

        win_count = len(wins)
        loss_count = len(losses)
        win_rate = (win_count / total * 100) if total > 0 else 0

        gross_profit = wins['realized_pnl'].sum() if not wins.empty else 0
        gross_loss = abs(losses['realized_pnl'].sum()) if not losses.empty else 0
        net_pnl = gross_profit - gross_loss

        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        # Drawdown from equity curve
        equity = self._build_equity_curve(closed_trades)
        max_dd, max_dd_pct = self._calculate_drawdown(equity)

        avg_win = wins['realized_pnl'].mean() if not wins.empty else 0
        avg_loss = losses['realized_pnl'].mean() if not losses.empty else 0
        largest_win = wins['realized_pnl'].max() if not wins.empty else 0
        largest_loss = losses['realized_pnl'].min() if not losses.empty else 0

        avg_trade = closed_trades['realized_pnl'].mean()
        expectancy = (win_rate/100 * avg_win) + ((1 - win_rate/100) * avg_loss) if total > 0 else 0

        # Ratios
        returns = closed_trades['realized_pnl'].tolist()
        sharpe = self._sharpe_ratio(returns)
        sortino = self._sortino_ratio(returns)
        calmar = self._calmar_ratio(net_pnl, max_dd)

        # Consecutive streaks
        streaks = self._calculate_streaks(closed_trades)

        report = PerformanceReport(
            period=f"Last {days} days",
            total_trades=total,
            winning_trades=win_count,
            losing_trades=loss_count,
            win_rate=win_rate,
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            net_pnl=net_pnl,
            profit_factor=profit_factor,
            max_drawdown=max_dd,
            max_drawdown_pct=max_dd_pct,
            avg_win=avg_win,
            avg_loss=avg_loss,
            largest_win=largest_win,
            largest_loss=largest_loss,
            avg_trade=avg_trade,
            expectancy=expectancy,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            consecutive_wins=streaks['max_wins'],
            consecutive_losses=streaks['max_losses']
        )

        # Save to database
        self.db.update_daily_performance(
            datetime.utcnow().date().isoformat(),
            report.to_dict()
        )

        self.logger.info(f"Report generated: {total} trades | P&L: ${net_pnl:.2f} | WR: {win_rate:.1f}%")

        return report

    def _build_equity_curve(self, trades_df: pd.DataFrame) -> List[float]:
        """Build equity curve from trade P&L"""
        if trades_df.empty:
            return [2000.0]

        trades_df = trades_df.sort_values('closed_at')
        equity = [2000.0]

        for _, trade in trades_df.iterrows():
            equity.append(equity[-1] + trade['realized_pnl'])

        return equity

    def _calculate_drawdown(self, equity: List[float]) -> tuple:
        """Calculate max drawdown and percentage"""
        peak = equity[0]
        max_dd = 0.0
        max_dd_pct = 0.0

        for val in equity:
            if val > peak:
                peak = val
            dd = peak - val
            if dd > max_dd:
                max_dd = dd
                max_dd_pct = (dd / peak * 100) if peak > 0 else 0

        return max_dd, max_dd_pct

    def _sharpe_ratio(self, returns: List[float], risk_free_rate: float = 0.0) -> float:
        """Calculate Sharpe ratio"""
        if not returns or len(returns) < 2:
            return 0.0

        excess_returns = [r - risk_free_rate for r in returns]
        mean = np.mean(excess_returns)
        std = np.std(excess_returns)

        return (mean / std * np.sqrt(252)) if std > 0 else 0.0

    def _sortino_ratio(self, returns: List[float], risk_free_rate: float = 0.0) -> float:
        """Calculate Sortino ratio (downside deviation only)"""
        if not returns or len(returns) < 2:
            return 0.0

        excess_returns = [r - risk_free_rate for r in returns]
        mean = np.mean(excess_returns)

        downside = [r for r in excess_returns if r < 0]
        downside_std = np.std(downside) if downside else 0.001

        return (mean / downside_std * np.sqrt(252)) if downside_std > 0 else 0.0

    def _calmar_ratio(self, net_pnl: float, max_dd: float) -> float:
        """Calculate Calmar ratio (annualized return / max drawdown)"""
        if max_dd <= 0:
            return float('inf')
        return (net_pnl / max_dd) if max_dd > 0 else 0.0

    def _calculate_streaks(self, trades_df: pd.DataFrame) -> Dict:
        """Calculate consecutive win/loss streaks"""
        if trades_df.empty:
            return {"max_wins": 0, "max_losses": 0}

        trades_df = trades_df.sort_values('closed_at')
        pnl_list = trades_df['realized_pnl'].tolist()

        max_wins = 0
        max_losses = 0
        current_wins = 0
        current_losses = 0

        for pnl in pnl_list:
            if pnl > 0:
                current_wins += 1
                current_losses = 0
                max_wins = max(max_wins, current_wins)
            else:
                current_losses += 1
                current_wins = 0
                max_losses = max(max_losses, current_losses)

        return {"max_wins": max_wins, "max_losses": max_losses}

    def _empty_report(self, period: str) -> PerformanceReport:
        """Return empty report"""
        return PerformanceReport(
            period=period, total_trades=0, winning_trades=0, losing_trades=0,
            win_rate=0, gross_profit=0, gross_loss=0, net_pnl=0,
            profit_factor=0, max_drawdown=0, max_drawdown_pct=0,
            avg_win=0, avg_loss=0, largest_win=0, largest_loss=0,
            avg_trade=0, expectancy=0, sharpe_ratio=0, sortino_ratio=0,
            calmar_ratio=0, consecutive_wins=0, consecutive_losses=0
        )

    def get_monthly_summary(self) -> pd.DataFrame:
        """Get monthly P&L summary"""
        trades = self.db.get_trades(limit=1000)
        if trades.empty or 'closed_at' not in trades.columns:
            return pd.DataFrame()

        trades['closed_at'] = pd.to_datetime(trades['closed_at'])
        trades['month'] = trades['closed_at'].dt.to_period('M')

        summary = trades.groupby('month').agg({
            'realized_pnl': ['sum', 'count', 'mean'],
            'exec_id': 'count'
        }).reset_index()

        summary.columns = ['month', 'net_pnl', 'avg_pnl', 'mean_pnl', 'trade_count']

        return summary

    def get_daily_summary(self, days: int = 30) -> pd.DataFrame:
        """Get daily P&L summary"""
        trades = self.db.get_trades(limit=1000)
        if trades.empty or 'closed_at' not in trades.columns:
            return pd.DataFrame()

        trades['closed_at'] = pd.to_datetime(trades['closed_at'])
        trades['date'] = trades['closed_at'].dt.date

        since = datetime.utcnow().date() - timedelta(days=days)
        trades = trades[trades['date'] >= since]

        summary = trades.groupby('date').agg({
            'realized_pnl': 'sum',
            'exec_id': 'count'
        }).reset_index()

        summary.columns = ['date', 'net_pnl', 'trade_count']

        return summary

    def print_report(self, report: PerformanceReport):
        """Print formatted report to console"""
        print("=" * 60)
        print(f"ULTRA PERFORMANCE REPORT - {report.period}")
        print("=" * 60)
        print(f"Total Trades:        {report.total_trades}")
        print(f"Winning Trades:      {report.winning_trades}")
        print(f"Losing Trades:       {report.losing_trades}")
        print(f"Win Rate:            {report.win_rate:.1f}%")
        print(f"Net P&L:             ${report.net_pnl:,.2f}")
        print(f"Gross Profit:        ${report.gross_profit:,.2f}")
        print(f"Gross Loss:          ${report.gross_loss:,.2f}")
        print(f"Profit Factor:       {report.profit_factor:.2f}")
        print(f"Max Drawdown:        ${report.max_drawdown:,.2f} ({report.max_drawdown_pct:.1f}%)")
        print(f"Average Win:         ${report.avg_win:,.2f}")
        print(f"Average Loss:        ${report.avg_loss:,.2f}")
        print(f"Largest Win:         ${report.largest_win:,.2f}")
        print(f"Largest Loss:        ${report.largest_loss:,.2f}")
        print(f"Expectancy:          ${report.expectancy:,.2f}")
        print(f"Sharpe Ratio:        {report.sharpe_ratio:.2f}")
        print(f"Sortino Ratio:       {report.sortino_ratio:.2f}")
        print(f"Calmar Ratio:        {report.calmar_ratio:.2f}")
        print(f"Consecutive Wins:    {report.consecutive_wins}")
        print(f"Consecutive Losses:  {report.consecutive_losses}")
        print("=" * 60)
