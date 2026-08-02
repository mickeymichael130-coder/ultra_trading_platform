"""
Tests for wiring config/settings.py into the orchestrator layers (iteration 4).
"""
import tempfile

import pytest

from src.orchestrator import TradingOrchestrator
from config.settings import BotConfig, IndicatorConfig, RiskConfig, StrategyConfig, ExecutionConfig


class RecordingBroker:
    """Captures constructor kwargs so broker wiring can be asserted."""

    def __init__(self, app_id=None, api_token=None, **kwargs):
        self.app_id = app_id
        self.api_token = api_token
        self.kwargs = kwargs

    def on_tick(self, handler):
        pass

    def on_candle(self, handler):
        pass

    async def disconnect(self):
        return None


def _build(settings=None, broker_cls=RecordingBroker):
    return TradingOrchestrator(
        symbols=["frxEURUSD"],
        mode="paper",
        db_path=tempfile.mkdtemp() + "/cfg.db",
        broker_cls=broker_cls,
        settings=settings,
    )


def test_default_settings_wire_into_layers():
    orch = _build()
    assert orch.settings is not None
    assert orch.strategy.min_atr_pips == 5.0
    assert orch.strategy.adx_threshold == 25.0
    assert orch.indicator_engine.ema_fast == 12
    assert orch.indicator_engine.ema_trend == 200
    assert orch.risk_manager.max_open_trades == 2
    assert orch.risk_manager.max_risk_per_trade_abs == 30.0
    assert orch.execution_engine.max_retries == 3
    assert orch.execution_engine.order_timeout == 10
    assert orch.candle_builder.timeframes == ["1m", "5m", "15m", "30m", "1h"]
    assert orch.signal_enhancer is not None


def test_custom_settings_propagate_to_layers():
    cfg = BotConfig()
    cfg.indicators = IndicatorConfig(ema_fast=10, ema_slow=30, ema_trend=180)
    cfg.risk = RiskConfig(max_open_trades=5, max_risk_per_trade_absolute=40.0,
                          cooldown_after_loss_minutes=10)
    cfg.strategy = StrategyConfig(min_atr_pips=8.0, trade_asian=True)
    cfg.execution = ExecutionConfig(max_order_retries=1, order_timeout_seconds=3)

    orch = _build(settings=cfg)

    assert orch.indicator_engine.ema_fast == 10
    assert orch.indicator_engine.ema_slow == 30
    assert orch.indicator_engine.ema_trend == 180
    assert orch.risk_manager.max_open_trades == 5
    assert orch.risk_manager.max_risk_per_trade_abs == 40.0
    assert orch.risk_manager.cooldown_after_loss_minutes == 10
    assert orch.strategy.min_atr_pips == 8.0
    assert orch.strategy.trade_asian is True
    assert orch.execution_engine.max_retries == 1
    assert orch.execution_engine.order_timeout == 3


def test_broker_gets_settings_kwargs():
    orch = _build()
    assert orch.broker.kwargs["reconnect_attempts"] == 10
    assert orch.broker.kwargs["heartbeat_interval"] == 30
    assert orch.broker.kwargs["reconnect_delay_base"] == 1.0


# === Broker selection (iteration 7: Binance integration) ===


def test_broker_type_binance_selects_client_and_crypto_symbols():
    from src.broker.binance_client import BinanceClient

    orch = TradingOrchestrator(
        mode="paper",
        db_path=tempfile.mkdtemp() + "/binance.db",
        broker_type="binance",
        broker_cls=BinanceClient,
    )
    assert orch.broker_type == "binance"
    assert orch.broker_cls is BinanceClient
    assert orch.symbols == ["BTCUSDT", "ETHUSDT"]


def test_broker_type_deriv_uses_forex_defaults():
    orch = TradingOrchestrator(
        mode="paper",
        db_path=tempfile.mkdtemp() + "/deriv.db",
        broker_cls=RecordingBroker,
    )
    assert orch.broker_type == "deriv"
    assert orch.symbols == ["frxEURUSD", "frxGBPUSD", "frxUSDJPY", "frxAUDUSD"]


def test_explicit_symbols_override_broker_defaults():
    orch = TradingOrchestrator(
        symbols=["BTCUSDT", "SOLUSDT"],
        mode="paper",
        db_path=tempfile.mkdtemp() + "/sym.db",
        broker_cls=RecordingBroker,
    )
    assert orch.symbols == ["BTCUSDT", "SOLUSDT"]


def test_custom_broker_cls_takes_precedence():
    orch = _build(broker_cls=RecordingBroker)
    assert orch.broker_cls is RecordingBroker


def test_signals_are_queryable(tmp_path):
    from src.database.manager import DatabaseManager

    db = DatabaseManager(str(tmp_path / "signals.db"))
    db.save_signal({
        "symbol": "frxEURUSD", "direction": "BUY", "strength": "strong",
        "confidence": 0.9, "timestamp": "2026-01-01 00:00:00",
        "strategy": "EMACrossover", "timeframe": "15m", "reason": "AI: bullish regime",
    }, risk_decision="accepted", risk_reason="ok")

    df = db.get_signals(limit=10)
    assert len(df) == 1
    assert df.iloc[0]["reason"] == "AI: bullish regime"
    assert df.iloc[0]["risk_decision"] == "accepted"


def test_get_signals_filters_by_symbol(tmp_path):
    from src.database.manager import DatabaseManager

    db = DatabaseManager(str(tmp_path / "signals2.db"))
    db.save_signal({"symbol": "frxEURUSD", "direction": "BUY", "strength": "strong",
                    "confidence": 0.8, "timestamp": "2026-01-01 00:00:00",
                    "strategy": "EMACrossover", "timeframe": "15m", "reason": "a"})
    db.save_signal({"symbol": "frxGBPUSD", "direction": "BUY", "strength": "weak",
                    "confidence": 0.6, "timestamp": "2026-01-01 00:00:00",
                    "strategy": "EMACrossover", "timeframe": "15m", "reason": "b"})

    eur = db.get_signals(symbol="frxEURUSD", limit=10)
    assert len(eur) == 1
    assert eur.iloc[0]["symbol"] == "frxEURUSD"
