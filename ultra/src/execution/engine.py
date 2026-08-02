"""
Execution Engine
Handles order placement, tracking, and confirmation.
Only approved signals reach this layer.
"""
from typing import Optional, Dict, Any
from datetime import datetime
import asyncio

from ..broker.deriv_client import DerivClient
from ..core.domain import (
    Signal as TradeSignal,
    SignalDirection,
    OrderStatus,
    ExecutionMode,
    Trade as TradeExecution,
)
from ..risk.manager import RiskResult
from ..utils.logger import get_logger


class ExecutionEngine:
    """
    Order Execution Engine.

    Responsibilities:
    - Execute approved signals
    - Track order lifecycle
    - Handle paper vs live mode
    - Retry failed orders
    - Record all executions
    """

    def __init__(
        self,
        broker: DerivClient,
        mode: ExecutionMode = ExecutionMode.PAPER,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        order_timeout: int = 10
    ):
        self.broker = broker
        self.mode = mode
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.order_timeout = order_timeout

        self.logger = get_logger("execution.engine")

        # Trade tracking
        self._active_trades: Dict[str, TradeExecution] = {}
        self._trade_history: list = []
        self._execution_counter = 0

        self.logger.info(f"ExecutionEngine initialized | Mode: {mode.value}")

    async def execute(self, risk_result: RiskResult) -> Optional[TradeExecution]:
        """
        Execute an approved trading signal.

        Args:
            risk_result: Approved risk result with sized signal

        Returns:
            TradeExecution record or None if failed
        """
        if risk_result.decision.value != "APPROVE":
            self.logger.warning("Cannot execute non-approved signal")
            return None

        signal = risk_result.modified_signal or risk_result.signal

        # Generate execution ID
        self._execution_counter += 1
        exec_id = f"EXEC_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{self._execution_counter}"

        execution = TradeExecution(
            id=exec_id,
            signal=signal,
            status=OrderStatus.PENDING,
            mode=self.mode,
            submitted_at=datetime.utcnow()
        )

        self.logger.info(
            f"Executing: {signal.symbol} {signal.direction.value} | "
            f"Mode: {self.mode.value} | ID: {exec_id}"
        )

        if self.mode == ExecutionMode.PAPER:
            result = await self._execute_paper(execution)
        else:
            result = await self._execute_live(execution)

        if result:
            self._active_trades[exec_id] = result
            self._trade_history.append(result)

        return result

    async def _execute_paper(self, execution: TradeExecution) -> Optional[TradeExecution]:
        """Execute in paper trading mode (simulated)"""
        signal = execution.signal

        try:
            # Simulate order processing delay
            await asyncio.sleep(0.5)

            # Paper fill at current price
            execution.status = OrderStatus.FILLED
            execution.entry_price = signal.entry_price
            execution.fill_price = signal.entry_price  # No slippage in paper
            execution.filled_at = datetime.utcnow()

            self.logger.info(
                f"📄 PAPER FILL: {signal.symbol} | "
                f"Price: {execution.fill_price:.5f} | "
                f"Size: {signal.position_size} | ID: {execution.id}"
            )

            return execution

        except Exception as e:
            execution.status = OrderStatus.ERROR
            execution.error_message = str(e)
            self.logger.error(f"Paper execution failed: {e}")
            return execution

    async def _execute_live(self, execution: TradeExecution) -> Optional[TradeExecution]:
        """Execute live order via Deriv API"""
        signal = execution.signal

        # Determine contract type based on direction
        # For Deriv forex, we use rise/fall or higher/lower
        contract_type = "CALL" if signal.direction == SignalDirection.BUY else "PUT"

        # Get proposal first (pricing)
        proposal = await self.broker.get_proposal(
            symbol=signal.symbol,
            contract_type=contract_type,
            amount=signal.risk_amount or 1.0,
            duration=15,  # 15 minutes for intraday
            duration_unit="m"
        )

        if not proposal or "proposal" not in proposal:
            execution.status = OrderStatus.ERROR
            execution.error_message = "Failed to get proposal"
            self.logger.error(f"Proposal failed for {signal.symbol}")
            return execution

        # Execute with retries
        for attempt in range(1, self.max_retries + 1):
            try:
                execution.status = OrderStatus.SUBMITTED
                execution.retry_count = attempt - 1

                result = await self.broker.buy_contract(
                    symbol=signal.symbol,
                    contract_type=contract_type,
                    amount=signal.risk_amount or 1.0,
                    duration=15,
                    duration_unit="m"
                )

                if result and "buy" in result:
                    execution.status = OrderStatus.FILLED
                    execution.contract_id = result["buy"].get("contract_id")
                    execution.entry_price = signal.entry_price
                    execution.fill_price = signal.entry_price
                    execution.filled_at = datetime.utcnow()

                    self.logger.info(
                        f"✅ LIVE FILL: {signal.symbol} | "
                        f"Contract: {execution.contract_id} | "
                        f"Price: {execution.fill_price:.5f} | ID: {execution.id}"
                    )

                    return execution
                else:
                    error = result.get("error", "Unknown error") if result else "No response"
                    self.logger.warning(f"Order attempt {attempt} failed: {error}")

                    if attempt < self.max_retries:
                        await asyncio.sleep(self.retry_delay * attempt)
                    else:
                        execution.status = OrderStatus.REJECTED
                        execution.error_message = str(error)

            except Exception as e:
                self.logger.error(f"Live execution error (attempt {attempt}): {e}")
                if attempt < self.max_retries:
                    await asyncio.sleep(self.retry_delay * attempt)
                else:
                    execution.status = OrderStatus.ERROR
                    execution.error_message = str(e)

        return execution

    async def close_trade(self, exec_id: str, exit_price: Optional[float] = None) -> Optional[TradeExecution]:
        """Close an active trade"""
        if exec_id not in self._active_trades:
            self.logger.warning(f"Trade not found: {exec_id}")
            return None

        execution = self._active_trades[exec_id]
        signal = execution.signal

        if self.mode == ExecutionMode.PAPER:
            # Paper close
            execution.status = OrderStatus.FILLED  # Mark as closed
            execution.exit_price = exit_price or signal.take_profit
            execution.closed_at = datetime.utcnow()

            # Calculate simulated P&L from pip movement and micro-lot size
            from ..utils.pips import pnl_from_price_move
            execution.pnl = pnl_from_price_move(
                signal.symbol, signal.direction.value,
                execution.fill_price, execution.exit_price,
                signal.position_size or 1.0
            )

            self.logger.info(
                f"📄 PAPER CLOSE: {signal.symbol} | "
                f"Exit: {execution.exit_price:.5f} | P&L: ${execution.pnl:.2f}"
            )

        else:
            # Live close via API
            if execution.contract_id:
                try:
                    result = await self.broker.sell_contract(execution.contract_id)
                    if result and "sell" in result:
                        execution.status = OrderStatus.FILLED
                        execution.exit_price = exit_price
                        execution.closed_at = datetime.utcnow()
                        execution.pnl = result["sell"].get("profit", 0)

                        self.logger.info(
                            f"✅ LIVE CLOSE: {signal.symbol} | "
                            f"P&L: ${execution.pnl:.2f}"
                        )
                    else:
                        execution.error_message = "Close failed"
                except Exception as e:
                    execution.error_message = str(e)
                    self.logger.error(f"Close failed: {e}")

        # Move to history
        if execution.status in [OrderStatus.FILLED, OrderStatus.ERROR]:
            del self._active_trades[exec_id]
            # Update in history
            for i, t in enumerate(self._trade_history):
                if t.id == exec_id:
                    self._trade_history[i] = execution
                    break

        return execution

    def get_active_trades(self) -> Dict[str, TradeExecution]:
        """Get all active trades"""
        return dict(self._active_trades)

    def get_trade_history(self) -> list:
        """Get trade history"""
        return list(self._trade_history)

    def get_trade(self, exec_id: str) -> Optional[TradeExecution]:
        """Get specific trade"""
        if exec_id in self._active_trades:
            return self._active_trades[exec_id]
        for t in self._trade_history:
            if t.id == exec_id:
                return t
        return None
