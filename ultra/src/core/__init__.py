"""Core package: broker-neutral domain models and platform primitives."""
from .domain import ConnectionState, MarketTick, Candle, Tick

__all__ = ["ConnectionState", "MarketTick", "Candle", "Tick"]
