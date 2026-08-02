"""
Position Manager
Manages open trades after entry.
Handles stop loss, take profit, trailing stop, break-even, time exit.
The strategy no longer controls the trade once opened.
"""
from typing import Optional, Dict, List
from datetime import datetime, timedelta
import asyncio

from ..core.domain import (
    SignalDirection,
    Trade as TradeExecution,
    Position,
    ExitReason,
)
from ..execution.engine import ExecutionEngine
from ..utils.logger import get_logger


class PositionManager:
    """
    Position Management Engine.

    Responsibilities:
    - Monitor open positions
    - Apply stop loss / take profit
    - Manage trailing stops
    - Move to break-even
    - Time-based exits
    - Coordinate with ExecutionEngine for closes

    Runs on a monitoring loop, checking positions against current prices.
    """

    def __init__(
        self,
        execution_engine: ExecutionEngine,
        trailing_stop_atr_multiplier: float = 1.0,
        break_even_atr_multiplier: float = 1.0,
        max_hold_minutes: int = 120,  # 2 hours max for intraday
        check_interval_seconds: float = 5.0
    ):
        self.execution_engine = execution_engine
        self.trailing_stop_atr_multiplier = trailing_stop_atr_multiplier
        self.break_even_atr_multiplier = break_even_atr_multiplier
        self.max_hold_time = timedelta(minutes=max_hold_minutes)
        self.check_interval = check_interval_seconds

        self.logger = get_logger("position.manager")

        # Position tracking
        self._positions: Dict[str, Position] = {}
        self._closed_positions: List[Position] = []

        # Price feed
        self._current_prices: Dict[str, float] = {}

        # Monitoring task
        self._monitoring = False
        self._monitor_task = None

        self.logger.info(
            f"PositionManager initialized | Max hold: {max_hold_minutes}min | "
            f"Check interval: {check_interval_seconds}s"
        )

    def on_price_update(self, symbol: str, price: float):
        """Receive price updates from data engine"""
        self._current_prices[symbol] = price

    def add_position(self, execution: TradeExecution) -> Position:
        """Add new position from execution"""
        signal = execution.signal

        position = Position(
            execution=execution,
            original_stop=signal.stop_loss or execution.entry_price * 0.99,
            original_target=signal.take_profit or execution.entry_price * 1.01,
            entry_time=execution.filled_at or datetime.utcnow(),
            current_stop=signal.stop_loss or execution.entry_price * 0.99,
            current_target=signal.take_profit or execution.entry_price * 1.01,
            max_hold_time=self.max_hold_time,
            trailing_stop_distance=(signal.atr or 0) * self.trailing_stop_atr_multiplier
        )

        self._positions[execution.id] = position

        self.logger.info(
            f"Position added: {signal.symbol} {signal.direction.value} | "
            f"Entry: {execution.fill_price:.5f} | "
            f"SL: {position.current_stop:.5f} | "
            f"TP: {position.current_target:.5f} | "
            f"ID: {execution.id}"
        )

        return position

    async def start_monitoring(self):
        """Start position monitoring loop"""
        self._monitoring = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        self.logger.info("Position monitoring started")

    async def stop_monitoring(self):
        """Stop position monitoring"""
        self._monitoring = False
        if self._monitor_task:
            self._monitor_task.cancel()
        self.logger.info("Position monitoring stopped")

    async def _monitor_loop(self):
        """Main monitoring loop"""
        while self._monitoring:
            try:
                for exec_id, position in list(self._positions.items()):
                    if position.is_closed:
                        continue

                    symbol = position.execution.signal.symbol
                    current_price = self._current_prices.get(symbol)

                    if current_price is None:
                        continue

                    # Update price extremes for trailing stop
                    self._update_price_extremes(position, current_price)

                    # Check all exit conditions
                    exit_triggered, reason = self._check_exit_conditions(position, current_price)

                    if exit_triggered:
                        await self._close_position(exec_id, current_price, reason)
                    else:
                        # Update trailing stop if applicable
                        self._update_trailing_stop(position, current_price)

                        # Check break-even move
                        self._check_break_even(position, current_price)

                await asyncio.sleep(self.check_interval)

            except Exception as e:
                self.logger.error(f"Monitor loop error: {e}")
                await asyncio.sleep(self.check_interval)

    def _update_price_extremes(self, position: Position, current_price: float):
        """Track highest/lowest price for trailing stop"""
        if position.execution.signal.direction == SignalDirection.BUY:
            if position.highest_price is None or current_price > position.highest_price:
                position.highest_price = current_price
        else:
            if position.lowest_price is None or current_price < position.lowest_price:
                position.lowest_price = current_price

    def _check_exit_conditions(self, position: Position, current_price: float) -> tuple:
        """
        Check all exit conditions.
        Returns: (exit_triggered, reason)
        """
        signal = position.execution.signal

        # 1. Stop Loss
        if signal.direction == SignalDirection.BUY:
            if current_price <= position.current_stop:
                return True, ExitReason.STOP_LOSS
        else:
            if current_price >= position.current_stop:
                return True, ExitReason.STOP_LOSS

        # 2. Take Profit
        if signal.direction == SignalDirection.BUY:
            if current_price >= position.current_target:
                return True, ExitReason.TAKE_PROFIT
        else:
            if current_price <= position.current_target:
                return True, ExitReason.TAKE_PROFIT

        # 3. Time Exit
        if position.max_hold_time:
            elapsed = datetime.utcnow() - position.entry_time
            if elapsed >= position.max_hold_time:
                return True, ExitReason.TIME_EXIT

        return False, None

    def _update_trailing_stop(self, position: Position, current_price: float):
        """Update trailing stop based on price movement"""
        if not position.trailing_stop_distance:
            return

        signal = position.execution.signal

        if signal.direction == SignalDirection.BUY:
            # For longs: trail below highest price
            if position.highest_price:
                new_stop = position.highest_price - position.trailing_stop_distance
                if new_stop > position.current_stop:
                    old_stop = position.current_stop
                    position.current_stop = new_stop
                    position.trailing_stop_active = True
                    self.logger.info(
                        f"Trailing stop updated: {signal.symbol} | "
                        f"{old_stop:.5f} → {new_stop:.5f}"
                    )
        else:
            # For shorts: trail above lowest price
            if position.lowest_price:
                new_stop = position.lowest_price + position.trailing_stop_distance
                if new_stop < position.current_stop:
                    old_stop = position.current_stop
                    position.current_stop = new_stop
                    position.trailing_stop_active = True
                    self.logger.info(
                        f"Trailing stop updated: {signal.symbol} | "
                        f"{old_stop:.5f} → {new_stop:.5f}"
                    )

    def _check_break_even(self, position: Position, current_price: float):
        """Move stop to break-even when profitable by ATR amount"""
        if position.break_even_triggered:
            return

        signal = position.execution.signal
        entry = position.execution.fill_price

        # Calculate break-even trigger distance
        atr_distance = (signal.atr or entry * 0.001) * self.break_even_atr_multiplier

        if signal.direction == SignalDirection.BUY:
            if current_price >= entry + atr_distance:
                position.current_stop = entry  # Move to break-even
                position.break_even_triggered = True
                position.break_even_level = entry
                self.logger.info(
                    f"Break-even triggered: {signal.symbol} | "
                    f"Stop moved to entry: {entry:.5f}"
                )
        else:
            if current_price <= entry - atr_distance:
                position.current_stop = entry
                position.break_even_triggered = True
                position.break_even_level = entry
                self.logger.info(
                    f"Break-even triggered: {signal.symbol} | "
                    f"Stop moved to entry: {entry:.5f}"
                )

    async def _close_position(self, exec_id: str, exit_price: float, reason: ExitReason):
        """Close position and record results"""
        position = self._positions.get(exec_id)
        if not position or position.is_closed:
            return

        position.is_closed = True
        position.exit_price = exit_price
        position.exit_time = datetime.utcnow()
        position.exit_reason = reason

        signal = position.execution.signal

        # Calculate P&L from pip movement and micro-lot size
        from ..utils.pips import pnl_from_price_move
        position.realized_pnl = pnl_from_price_move(
            signal.symbol, signal.direction.value,
            position.execution.fill_price, exit_price,
            signal.position_size or 1.0
        )

        # Execute close via execution engine
        await self.execution_engine.close_trade(exec_id, exit_price)

        # Move to closed positions
        self._closed_positions.append(position)
        del self._positions[exec_id]

        self.logger.info(
            f"Position closed: {signal.symbol} | "
            f"Reason: {reason.value} | "
            f"Exit: {exit_price:.5f} | "
            f"P&L: ${position.realized_pnl:.2f} | "
            f"Hold time: {position.exit_time - position.entry_time}"
        )

    def get_position(self, exec_id: str) -> Optional[Position]:
        """Get active position"""
        return self._positions.get(exec_id)

    def get_all_positions(self) -> Dict[str, Position]:
        """Get all active positions"""
        return dict(self._positions)

    def get_closed_positions(self) -> List[Position]:
        """Get closed positions history"""
        return list(self._closed_positions)

    def get_position_summary(self) -> Dict:
        """Get position summary"""
        active_count = len(self._positions)
        closed_count = len(self._closed_positions)

        total_pnl = sum(p.realized_pnl or 0 for p in self._closed_positions)
        winning_trades = sum(1 for p in self._closed_positions if (p.realized_pnl or 0) > 0)
        losing_trades = sum(1 for p in self._closed_positions if (p.realized_pnl or 0) < 0)

        return {
            "active_positions": active_count,
            "closed_positions": closed_count,
            "total_pnl": total_pnl,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": (winning_trades / closed_count * 100) if closed_count > 0 else 0
        }
