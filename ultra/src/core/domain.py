"""
Broker-neutral core domain models (ADR-002).

Strategies, risk and execution logic operate on these objects and never on
broker-specific types. Each broker adapter translates between these models and
the broker's API. See docs/02_Domain_Model.md.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, Optional


class ConnectionState(Enum):
    """Connection lifecycle shared by all broker adapters."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    AUTHENTICATED = "authenticated"
    RECONNECTING = "reconnecting"
    ERROR = "error"


@dataclass
class MarketTick:
    """A single market tick (broker-neutral). Timestamp is epoch ms."""
    symbol: str
    price: float
    timestamp: int  # Unix epoch ms
    bid: Optional[float] = None
    ask: Optional[float] = None
    pip_size: float = 0.0001  # For forex

    @property
    def spread(self) -> Optional[float]:
        if self.bid and self.ask:
            return self.ask - self.bid
        return None

    @property
    def mid(self) -> float:
        if self.bid and self.ask:
            return (self.bid + self.ask) / 2
        return self.price


@dataclass
class Candle:
    """A single OHLC candle (broker-neutral). Epoch is candle open time in
    seconds."""
    symbol: str
    timeframe: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    epoch: int  # Candle open time, seconds

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "epoch": self.epoch
        }


# Back-compat alias: Tick was historically the name used by the Deriv client
# and throughout the codebase. Keep it so existing imports keep working while
# the platform migrates to the broker-neutral MarketTick name.
Tick = MarketTick


class SignalDirection(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class SignalStrength(Enum):
    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"


@dataclass
class Signal:
    """Broker-neutral trading signal (was TradeSignal)."""
    symbol: str
    direction: SignalDirection
    strength: SignalStrength
    confidence: float  # 0.0 to 1.0
    timestamp: Any  # epoch ms preferred; strategies may pass pd.Timestamp

    # Entry/Exit parameters
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    atr: Optional[float] = None

    # Strategy metadata
    strategy_name: str = ""
    timeframe: str = ""
    reason: str = ""

    # Risk parameters
    risk_amount: Optional[float] = None
    position_size: Optional[float] = None

    def is_valid(self) -> bool:
        return self.direction != SignalDirection.HOLD and self.confidence >= 0.5

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "direction": self.direction.value,
            "strength": self.strength.value,
            "confidence": round(self.confidence, 3),
            "timestamp": str(self.timestamp),
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "atr": self.atr,
            "strategy": self.strategy_name,
            "timeframe": self.timeframe,
            "reason": self.reason,
            "risk_amount": self.risk_amount,
            "position_size": self.position_size
        }


class OrderStatus(Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIAL = "partial"
    REJECTED = "rejected"
    ERROR = "error"
    CANCELLED = "cancelled"


class ExecutionMode(Enum):
    PAPER = "paper"
    LIVE = "live"


@dataclass
class Trade:
    """Broker-neutral record of a trade execution (was TradeExecution)."""
    id: str
    signal: Signal
    status: OrderStatus
    mode: ExecutionMode

    # Order details
    contract_id: Optional[str] = None
    entry_price: Optional[float] = None
    fill_price: Optional[float] = None

    # Timing
    submitted_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None

    # Results
    pnl: Optional[float] = None
    exit_price: Optional[float] = None
    closed_at: Optional[datetime] = None

    # Error tracking
    error_message: Optional[str] = None
    retry_count: int = 0

    def to_dict(self) -> Dict:
        signal = self.signal
        return {
            "id": self.id,
            "exec_id": self.id,
            "symbol": signal.symbol,
            "direction": signal.direction.value,
            "status": self.status.value,
            "mode": self.mode.value,
            "entry_price": self.entry_price,
            "fill_price": self.fill_price,
            "pnl": self.pnl,
            "realized_pnl": self.pnl,
            "submitted_at": str(self.submitted_at) if self.submitted_at else None,
            "filled_at": str(self.filled_at) if self.filled_at else None,
            "opened_at": str(self.filled_at) if self.filled_at else None,
            "closed_at": str(self.closed_at) if self.closed_at else None,
            "error": self.error_message,
            # Signal-derived fields required by the trades table.
            "strategy": signal.strategy_name,
            "timeframe": signal.timeframe,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "position_size": signal.position_size,
            "risk_amount": signal.risk_amount,
            "confidence": signal.confidence,
            "reason": signal.reason,
        }


class ExitReason(Enum):
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    TRAILING_STOP = "trailing_stop"
    BREAK_EVEN = "break_even"
    TIME_EXIT = "time_exit"
    MANUAL = "manual"


@dataclass
class Position:
    """Broker-neutral active position with dynamic management state."""
    execution: Trade

    # Original levels
    original_stop: float
    original_target: float
    entry_time: datetime

    # Current levels (may be modified)
    current_stop: float
    current_target: float

    # Trailing stop
    trailing_stop_active: bool = False
    trailing_stop_distance: Optional[float] = None
    highest_price: Optional[float] = None
    lowest_price: Optional[float] = None

    # Break-even
    break_even_triggered: bool = False
    break_even_level: Optional[float] = None

    # Time exit
    max_hold_time: Optional[timedelta] = None

    # Status
    is_closed: bool = False
    exit_reason: Optional[ExitReason] = None
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    realized_pnl: Optional[float] = None


@dataclass
class Account:
    """Broker-neutral account snapshot."""
    broker: str
    balance: float
    currency: str = "USD"
    available_balance: Optional[float] = None
    equity: Optional[float] = None
    updated_at: Optional[datetime] = None


# Back-compat aliases: keep the historical names working everywhere while the
# platform migrates to the broker-neutral model names.
TradeSignal = Signal
TradeExecution = Trade
