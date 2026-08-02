"""
Broker Interface (BaseBroker).

The contract every broker adapter implements so the trading engine never
depends on a specific broker (ADR-001 / ADR-002). See
docs/phases/Phase_02_Broker_Framework.md.

Adapters own all broker protocol details and translate to/from the
broker-neutral core domain models (MarketTick, Candle).
"""
from abc import ABC, abstractmethod
from typing import Callable, Dict, List, Optional

from ..core.domain import Account, Candle, MarketTick


class BaseBroker(ABC):
    """Common interface for market-data + order brokers."""

    # === Connection Management ===

    @abstractmethod
    async def connect(self) -> bool:
        """Establish the connection; return True on success."""

    @abstractmethod
    async def disconnect(self):
        """Gracefully close the connection and stop background tasks."""

    # === Registration Methods ===

    @abstractmethod
    def on_tick(self, handler: Callable[[MarketTick], None]):
        """Register a handler for incoming ticks."""

    @abstractmethod
    def on_candle(self, handler: Callable[[Candle], None]):
        """Register a handler for incoming candles (streaming + history)."""

    @abstractmethod
    def on_error(self, handler: Callable[[Dict], None]):
        """Register a handler for broker errors."""

    # === Market Data ===

    @abstractmethod
    async def subscribe_ticks(self, symbol: str):
        """Subscribe to real-time ticks for a symbol."""

    @abstractmethod
    async def subscribe_candles(self, symbol: str, timeframe: str = "1m",
                                history_count: int = 500):
        """Subscribe to candle updates and return a history dict of shape
        {"candles": [Candle.to_dict(), ...]} for seeding."""

    @abstractmethod
    async def fetch_history(self, symbol: str, timeframe: str = "1m",
                            count: int = 500) -> Optional[Dict]:
        """One-shot historical candle fetch (no subscription)."""

    @abstractmethod
    async def unsubscribe_all(self):
        """Unsubscribe from all active streams."""

    # === Trading (live brokers) ===

    @abstractmethod
    async def buy_contract(self, *args, **kwargs) -> Optional[Dict]:
        """Place a buy order (broker contract model)."""

    @abstractmethod
    async def sell_contract(self, *args, **kwargs) -> Optional[Dict]:
        """Close an open position/contract."""

    @abstractmethod
    async def get_proposal(self, *args, **kwargs) -> Optional[Dict]:
        """Get pricing/proposal before buying."""

    # === Liveness / Account ===

    @abstractmethod
    async def ping(self) -> Optional[float]:
        """Round-trip latency of a broker request in milliseconds."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Whether the broker connection is usable."""

    @property
    @abstractmethod
    def account_balance(self) -> Optional[float]:
        """Current account balance, or None when unavailable (e.g. public data)."""

    @abstractmethod
    async def get_balance(self) -> Optional[Account]:
        """Fetch a broker-neutral Account snapshot, or None when unavailable."""
