"""
Tests for the broker abstraction layer (iteration 9, ADR-001/ADR-002):
BaseBroker ABC contract, broker factory, and broker-neutral domain models.
"""
import asyncio

import pytest

from src.broker.base_broker import BaseBroker
from src.broker.broker_factory import get_broker_class, available_brokers
from src.broker import DerivClient, BinanceClient
from src.core.domain import (
    ConnectionState, MarketTick, Candle, Tick,
    Signal, SignalDirection, SignalStrength,
    OrderStatus, ExecutionMode, Trade, Position, Account, ExitReason,
    TradeSignal, TradeExecution,
)
from src.strategies.ema_crossover import TradeSignal as StgTradeSignal
from src.execution.engine import TradeExecution as EngTradeExecution


# === BaseBroker ABC ===


def test_broker_clients_subclass_basebroker():
    assert issubclass(DerivClient, BaseBroker)
    assert issubclass(BinanceClient, BaseBroker)


def test_basebroker_is_abstract():
    with pytest.raises(TypeError):
        BaseBroker()


def test_basebroker_requires_connect_and_disconnect():
    class MissingMethods(BaseBroker):
        pass

    with pytest.raises(TypeError):
        MissingMethods()


# === Broker factory ===


def test_factory_returns_known_brokers():
    assert get_broker_class("deriv") is DerivClient
    assert get_broker_class("binance") is BinanceClient
    assert get_broker_class("BINANCE") is BinanceClient  # case-insensitive


def test_factory_falls_back_to_deriv():
    assert get_broker_class("bogus") is DerivClient
    assert get_broker_class("") is DerivClient
    assert get_broker_class(None) is DerivClient


def test_available_brokers():
    brokers = available_brokers()
    assert "deriv" in brokers
    assert "binance" in brokers


# === Domain models ===


def test_tick_is_markettick_alias():
    assert Tick is MarketTick


def test_markettick_mid_and_spread():
    tick = MarketTick(symbol="BTCUSDT", price=100.0, timestamp=1, bid=99.0, ask=101.0)
    assert tick.mid == 100.0
    assert tick.spread == 2.0
    assert tick.pip_size == 0.0001  # default

    no_quote = MarketTick(symbol="BTCUSDT", price=100.0, timestamp=1)
    assert no_quote.mid == 100.0
    assert no_quote.spread is None


def test_candle_to_dict():
    c = Candle(symbol="frxEURUSD", timeframe="15m", open=1.1, high=1.11,
               low=1.09, close=1.105, volume=10, epoch=1700000000)
    d = c.to_dict()
    assert d["symbol"] == "frxEURUSD"
    assert d["volume"] == 10
    assert d["epoch"] == 1700000000


def test_connection_state_values():
    assert ConnectionState.AUTHENTICATED.value == "authenticated"
    assert ConnectionState.RECONNECTING.value == "reconnecting"


def test_basebroker_contract_methods_exist_on_clients():
    for cls in (DerivClient, BinanceClient):
        for method in ("connect", "disconnect", "subscribe_ticks",
                       "subscribe_candles", "fetch_history", "unsubscribe_all",
                       "buy_contract", "sell_contract", "get_proposal", "ping"):
            assert callable(getattr(cls, method)), f"{cls.__name__}.{method}"
        # is_connected / account_balance are properties
        assert isinstance(getattr(cls, "is_connected"), property)
        assert isinstance(getattr(cls, "account_balance"), property)


# === Signal / Trade / Position / Account (ADR-002 migration) ===


def test_signal_backcompat_aliases_resolve_to_domain_signal():
    assert TradeSignal is Signal
    assert StgTradeSignal is Signal  # via src.strategies.ema_crossover re-export


def test_trade_backcompat_aliases_resolve_to_domain_trade():
    assert TradeExecution is Trade
    assert EngTradeExecution is Trade  # via src.execution.engine re-export


def test_signal_is_valid_and_to_dict():
    s = Signal(symbol="frxEURUSD", direction=SignalDirection.BUY,
               strength=SignalStrength.MODERATE, confidence=0.8,
               timestamp=1234567890, entry_price=1.10, stop_loss=1.09,
               take_profit=1.12, strategy_name="t", timeframe="15m")
    assert s.is_valid()
    d = s.to_dict()
    assert d["direction"] == "BUY"
    assert d["symbol"] == "frxEURUSD"
    assert d["strategy"] == "t"


def test_trade_to_dict_has_db_fields():
    sig = Signal(symbol="frxEURUSD", direction=SignalDirection.SELL,
                 strength=SignalStrength.STRONG, confidence=0.9,
                 timestamp=1234567890)
    t = Trade(id="EXEC_1", signal=sig, status=OrderStatus.FILLED,
              mode=ExecutionMode.PAPER, fill_price=1.1, pnl=2.5)
    d = t.to_dict()
    for key in ("exec_id", "realized_pnl", "opened_at", "strategy",
                "stop_loss", "take_profit", "position_size", "confidence", "reason"):
        assert key in d
    assert d["mode"] == "paper"
    assert d["direction"] == "SELL"


def test_position_defaults_and_exit_reason():
    sig = Signal(symbol="frxEURUSD", direction=SignalDirection.BUY,
                 strength=SignalStrength.MODERATE, confidence=0.7, timestamp=1)
    trade = Trade(id="EXEC_1", signal=sig, status=OrderStatus.FILLED,
                  mode=ExecutionMode.PAPER)
    pos = Position(execution=trade, original_stop=1.09, original_target=1.12,
                   entry_time=None, current_stop=1.09, current_target=1.12)
    assert pos.is_closed is False
    assert pos.trailing_stop_active is False
    assert pos.max_hold_time is None
    assert pos.exit_reason is None
    assert ExitReason.STOP_LOSS.value == "stop_loss"


def test_account_model():
    acc = Account(broker="binance", balance=2000.0, currency="USD")
    assert acc.broker == "binance"
    assert acc.available_balance is None
    assert acc.equity is None
