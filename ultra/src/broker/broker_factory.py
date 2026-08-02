"""
Broker factory (ADR-001 / docs/03_Project_Structure.md).

Maps a broker_type string to its adapter class so the orchestrator and CLI can
select a broker with zero engine changes.
"""
from typing import Type

from .base_broker import BaseBroker
from .binance_client import BinanceClient
from .deriv_client import DerivClient

_BROKERS: dict = {
    "deriv": DerivClient,
    "binance": BinanceClient,
}


def get_broker_class(broker_type: str) -> Type[BaseBroker]:
    """Return the broker adapter class for a broker_type (case-insensitive).

    Unknown types fall back to Deriv so the platform never crashes on a typo.
    """
    return _BROKERS.get((broker_type or "deriv").lower(), DerivClient)


def available_brokers() -> list:
    """Names of registered broker adapters (for CLI help / config)."""
    return list(_BROKERS)
