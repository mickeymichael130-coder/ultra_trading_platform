"""
Configuration Manager for Deriv Trading Bot
All settings centralized. No hardcoded values elsewhere.
"""
import os
from dataclasses import dataclass, field
from typing import List, Dict
from enum import Enum


class TradingMode(Enum):
    PAPER = "paper"
    LIVE = "live"
    BACKTEST = "backtest"


class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass
class BrokerConfig:
    """Broker API Configuration (Deriv or Binance)"""
    broker_type: str = field(default_factory=lambda: os.getenv("BROKER", "deriv"))
    app_id: str = field(default_factory=lambda: os.getenv("DERIV_APP_ID", ""))
    api_token: str = field(default_factory=lambda: os.getenv("DERIV_API_TOKEN", ""))
    websocket_url: str = "wss://ws.derivws.com/websockets/v3"
    reconnect_attempts: int = 10
    reconnect_delay_base: float = 1.0  # seconds
    reconnect_delay_max: float = 60.0
    heartbeat_interval: int = 30  # seconds

    # Forex pairs to trade (Deriv)
    symbols: List[str] = field(default_factory=lambda: [
        "frxEURUSD", "frxGBPUSD", "frxUSDJPY", "frxAUDUSD"
    ])


@dataclass
class DataEngineConfig:
    """Market Data Configuration"""
    # Timeframes
    tick_buffer_size: int = 1000
    candle_timeframes: List[str] = field(default_factory=lambda: ["1m", "5m", "15m", "30m", "1h"])

    # Aggregation settings
    max_candles_in_memory: int = 5000  # per symbol per timeframe

    # Session awareness (UTC)
    london_session_start: int = 8   # 08:00 UTC
    london_session_end: int = 17    # 17:00 UTC
    ny_session_start: int = 13      # 13:00 UTC
    ny_session_end: int = 22        # 22:00 UTC


@dataclass
class IndicatorConfig:
    """Technical Indicator Parameters"""
    # EMA
    ema_fast: int = 12
    ema_slow: int = 26
    ema_trend: int = 200

    # RSI
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0

    # ATR
    atr_period: int = 14
    atr_multiplier_sl: float = 1.5  # Stop Loss multiplier
    atr_multiplier_tp: float = 2.5  # Take Profit multiplier

    # MACD
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9

    # Bollinger Bands
    bb_period: int = 20
    bb_std: float = 2.0

    # ADX
    adx_period: int = 14
    adx_threshold: float = 25.0


@dataclass
class RiskConfig:
    """Risk Management - HARD CONSTRAINTS for $2000 account"""
    # Capital
    initial_capital: float = 2000.0

    # Per-trade limits
    max_risk_per_trade_pct: float = 1.5  # $30 max
    max_risk_per_trade_absolute: float = 30.0

    # Daily limits
    max_daily_loss_pct: float = 3.0  # $60 max
    max_daily_loss_absolute: float = 60.0

    # Drawdown
    max_drawdown_pct: float = 10.0  # $200 max → KILL SWITCH
    max_drawdown_absolute: float = 200.0

    # Trade limits
    max_open_trades: int = 2
    max_trades_per_day: int = 6

    # Cooldown
    cooldown_after_loss_minutes: int = 15

    # Correlation
    max_correlated_trades: int = 1  # Don't trade EUR/USD and GBP/USD simultaneously

    # Leverage (effective, not Deriv's max)
    effective_leverage: float = 50.0


@dataclass
class StrategyConfig:
    """Strategy Parameters"""
    # Primary timeframe for signals
    primary_timeframe: str = "15m"

    # Confirmation timeframe
    confirmation_timeframe: str = "1h"

    # Minimum ATR for valid setup (filters low volatility)
    min_atr_pips: float = 5.0

    # Session filter
    trade_london: bool = True
    trade_ny: bool = True
    trade_asian: bool = False  # Avoid false breakouts

    # Signal confidence threshold
    min_confidence: float = 0.6


@dataclass
class ExecutionConfig:
    """Order Execution Settings"""
    # Slippage tolerance in pips
    max_slippage_pips: float = 2.0

    # Order timeout
    order_timeout_seconds: int = 10

    # Retry settings
    max_order_retries: int = 3
    retry_delay_seconds: float = 1.0

    # Partial fill handling
    allow_partial_fills: bool = False


@dataclass
class DatabaseConfig:
    """Database Configuration"""
    # SQLite for local state (fast, simple)
    sqlite_path: str = "data/ultra.db"

    # PostgreSQL for analytics (optional, for production)
    postgres_host: str = field(default_factory=lambda: os.getenv("POSTGRES_HOST", "localhost"))
    postgres_port: int = 5432
    postgres_db: str = field(default_factory=lambda: os.getenv("POSTGRES_DB", "trading_bot"))
    postgres_user: str = field(default_factory=lambda: os.getenv("POSTGRES_USER", "bot"))
    postgres_password: str = field(default_factory=lambda: os.getenv("POSTGRES_PASSWORD", ""))

    # Retention
    candle_retention_days: int = 365
    trade_retention_days: int = 2555  # 7 years


@dataclass
class MonitoringConfig:
    """System Monitoring"""
    # Health check interval
    health_check_interval_seconds: int = 30

    # Alert thresholds
    max_latency_ms: int = 500
    max_cpu_percent: float = 80.0
    max_ram_percent: float = 85.0

    # Notification (extendable)
    alert_email: str = field(default_factory=lambda: os.getenv("ALERT_EMAIL", ""))
    webhook_url: str = field(default_factory=lambda: os.getenv("WEBHOOK_URL", ""))


@dataclass
class BotConfig:
    """Master Configuration Container"""
    trading_mode: TradingMode = TradingMode.PAPER
    log_level: LogLevel = LogLevel.INFO

    broker: BrokerConfig = field(default_factory=BrokerConfig)
    data_engine: DataEngineConfig = field(default_factory=DataEngineConfig)
    indicators: IndicatorConfig = field(default_factory=IndicatorConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)

    # Bot identity
    bot_name: str = "ULTRA_v1"
    version: str = "1.0.0"


# Global config instance
config = BotConfig()


def load_config_from_env():
    """Override config with environment variables"""
    mode = os.getenv("TRADING_MODE", "paper").lower()
    if mode == "live":
        config.trading_mode = TradingMode.LIVE
    elif mode == "backtest":
        config.trading_mode = TradingMode.BACKTEST
    else:
        config.trading_mode = TradingMode.PAPER

    level = os.getenv("LOG_LEVEL", "INFO").upper()
    config.log_level = LogLevel[level]

    return config
