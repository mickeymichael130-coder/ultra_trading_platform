"""
Tests for Phase 7 (Execution Engine, paper mode) and Phase 8 (Position Manager).
"""
import asyncio

import pandas as pd
import pytest

from src.strategies.ema_crossover import TradeSignal, SignalDirection, SignalStrength
from src.risk.manager import RiskManager, RiskDecision
from src.execution.engine import ExecutionEngine, ExecutionMode, OrderStatus
from src.position_manager.manager import PositionManager, ExitReason


class StubBroker:
    """Minimal broker stub — paper execution never touches the network."""
    async def buy_contract(self, *a, **k): return None
    async def sell_contract(self, *a, **k): return None
    async def get_proposal(self, *a, **k): return None


def make_signal():
    return TradeSignal(
        symbol="frxEURUSD",
        direction=SignalDirection.BUY,
        strength=SignalStrength.MODERATE,
        confidence=0.8,
        timestamp=pd.Timestamp("2026-01-01", tz="UTC"),
        entry_price=1.1000,
        stop_loss=1.0985,
        take_profit=1.1040,
        atr=0.0012,
        strategy_name="test",
        timeframe="15m",
    )


def approved_risk_result():
    rm = RiskManager(initial_capital=2000.0)
    return rm.evaluate(make_signal(), 2000.0)


@pytest.mark.asyncio
async def test_paper_execution_fills():
    engine = ExecutionEngine(broker=StubBroker(), mode=ExecutionMode.PAPER)
    result = approved_risk_result()
    execution = await engine.execute(result)

    assert execution is not None
    assert execution.status == OrderStatus.FILLED
    assert execution.mode == ExecutionMode.PAPER
    assert execution.fill_price == execution.signal.entry_price
    assert execution.id in engine.get_active_trades()
    assert execution.order is not None
    assert execution.order.status == OrderStatus.FILLED
    assert execution.order.symbol == "frxEURUSD"
    assert execution.order.fill_price == execution.fill_price


@pytest.mark.asyncio
async def test_rejects_non_approved():
    engine = ExecutionEngine(broker=StubBroker(), mode=ExecutionMode.PAPER)
    rm = RiskManager(initial_capital=2000.0)
    rm._kill_switch_active = True
    rejected = rm.evaluate(make_signal(), 2000.0)
    assert not rejected.is_approved
    assert await engine.execute(rejected) is None


@pytest.mark.asyncio
async def test_paper_close_calculates_pnl():
    engine = ExecutionEngine(broker=StubBroker(), mode=ExecutionMode.PAPER)
    execution = await engine.execute(approved_risk_result())
    closed = await engine.close_trade(execution.id, exit_price=1.1050)

    assert closed is not None
    assert closed.exit_price == 1.1050
    assert closed.pnl > 0
    assert execution.id not in engine.get_active_trades()


@pytest.mark.asyncio
async def test_position_manager_exits_on_stop_loss():
    engine = ExecutionEngine(broker=StubBroker(), mode=ExecutionMode.PAPER)
    execution = await engine.execute(approved_risk_result())
    pm = PositionManager(execution_engine=engine)
    pm.add_position(execution)

    # Price tanks through the stop
    pm.on_price_update("frxEURUSD", 1.0980)
    exit_triggered, reason = pm._check_exit_conditions(
        pm.get_position(execution.id), 1.0980
    )
    assert exit_triggered
    assert reason == ExitReason.STOP_LOSS


@pytest.mark.asyncio
async def test_position_manager_takes_profit():
    engine = ExecutionEngine(broker=StubBroker(), mode=ExecutionMode.PAPER)
    execution = await engine.execute(approved_risk_result())
    pm = PositionManager(execution_engine=engine)
    pm.add_position(execution)

    pm.on_price_update("frxEURUSD", 1.1050)
    exit_triggered, reason = pm._check_exit_conditions(
        pm.get_position(execution.id), 1.1050
    )
    assert exit_triggered
    assert reason == ExitReason.TAKE_PROFIT


@pytest.mark.asyncio
async def test_break_even_moves_stop_to_entry():
    engine = ExecutionEngine(broker=StubBroker(), mode=ExecutionMode.PAPER)
    execution = await engine.execute(approved_risk_result())
    pm = PositionManager(execution_engine=engine)
    pm.add_position(execution)
    position = pm.get_position(execution.id)

    # Price rises more than ATR → stop should move to entry
    entry = position.execution.fill_price
    pm._check_break_even(position, entry + 0.003)
    assert position.break_even_triggered
    assert position.current_stop == entry
