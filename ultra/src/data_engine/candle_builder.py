"""
Candle Builder & Market Data Engine
Transforms raw ticks into OHLC candles across multiple timeframes.
Maintains in-memory buffers and handles session awareness.
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Callable
from collections import deque
from datetime import datetime, timezone
import threading

from ..core.domain import Tick, Candle
from ..utils.logger import get_logger
from ..utils.pips import is_crypto_symbol


class CandleBuilder:
    """
    Builds OHLC candles from tick stream.
    Supports multiple timeframes simultaneously.
    """

    def __init__(
        self,
        timeframes: List[str] = None,
        max_candles: int = 5000,
        tick_buffer_size: int = 1000
    ):
        self.timeframes = timeframes or ["1m", "5m", "15m", "30m", "1h"]
        self.max_candles = max_candles
        self.tick_buffer_size = tick_buffer_size

        self.logger = get_logger("data_engine.candle_builder")

        # Timeframe to seconds mapping
        self._tf_seconds = {
            "1m": 60, "5m": 300, "15m": 900,
            "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400
        }

        # Per-symbol, per-timeframe candle storage
        # Structure: {symbol: {timeframe: deque([Candle, ...])}}
        self._candles: Dict[str, Dict[str, deque]] = {}

        # Current incomplete candles
        # Structure: {symbol: {timeframe: Candle}}
        self._current_candles: Dict[str, Dict[str, Optional[Candle]]] = {}

        # Tick buffer for recent ticks
        self._tick_buffer: Dict[str, deque] = {}

        # Candle completion handlers
        self._candle_complete_handlers: List[Callable[[Candle], None]] = []

        # Lock for thread safety
        self._lock = threading.RLock()

        self.logger.info(f"CandleBuilder initialized | Timeframes: {self.timeframes}")

    def register_symbol(self, symbol: str):
        """Initialize storage for a new symbol"""
        with self._lock:
            if symbol not in self._candles:
                self._candles[symbol] = {}
                self._current_candles[symbol] = {}
                self._tick_buffer[symbol] = deque(maxlen=self.tick_buffer_size)

                for tf in self.timeframes:
                    self._candles[symbol][tf] = deque(maxlen=self.max_candles)
                    self._current_candles[symbol][tf] = None

                self.logger.info(f"Registered symbol: {symbol}")

    def on_tick(self, tick: Tick):
        """Process incoming tick"""
        with self._lock:
            symbol = tick.symbol

            if symbol not in self._candles:
                self.register_symbol(symbol)

            # Store tick
            self._tick_buffer[symbol].append({
                "price": tick.mid,
                "timestamp": tick.timestamp,
                "bid": tick.bid,
                "ask": tick.ask
            })

            # Update candles for all timeframes
            for tf in self.timeframes:
                self._update_candle(symbol, tf, tick)

    def _update_candle(self, symbol: str, timeframe: str, tick: Tick):
        """Update or create candle for given timeframe"""
        tick_time = tick.timestamp / 1000  # Convert ms to seconds
        candle_epoch = self._get_candle_epoch(tick_time, timeframe)

        current = self._current_candles[symbol][timeframe]

        if current is None or current.epoch != candle_epoch:
            # New candle period started
            if current is not None:
                # Finalize previous candle
                self._finalize_candle(symbol, timeframe, current)

            # Create new candle
            price = tick.mid
            new_candle = Candle(
                symbol=symbol,
                timeframe=timeframe,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=1,
                epoch=candle_epoch
            )
            self._current_candles[symbol][timeframe] = new_candle
        else:
            # Update existing candle
            current.high = max(current.high, tick.mid)
            current.low = min(current.low, tick.mid)
            current.close = tick.mid
            current.volume += 1

    def _finalize_candle(self, symbol: str, timeframe: str, candle: Candle):
        """Finalize a completed candle and notify handlers"""
        self._candles[symbol][timeframe].append(candle)

        self.logger.debug(
            f"Candle complete: {symbol} {timeframe} | "
            f"O:{candle.open:.5f} H:{candle.high:.5f} "
            f"L:{candle.low:.5f} C:{candle.close:.5f}"
        )

        # Notify handlers
        for handler in self._candle_complete_handlers:
            try:
                handler(candle)
            except Exception as e:
                self.logger.error(f"Candle handler error: {e}")

    def _get_candle_epoch(self, timestamp: float, timeframe: str) -> int:
        """Get the epoch (open time) for a given timestamp and timeframe"""
        seconds = self._tf_seconds[timeframe]
        return int(timestamp // seconds) * seconds

    def on_candle_complete(self, handler: Callable[[Candle], None]):
        """Register handler for completed candles"""
        self._candle_complete_handlers.append(handler)

    def seed_history(self, symbol: str, timeframe: str, candles: List[Candle]):
        """
        Seed the buffer with historical candles from the broker.
        Only seeds when the buffer is still empty so live tick-built
        candles are never duplicated or overwritten.
        """
        with self._lock:
            if symbol not in self._candles:
                self.register_symbol(symbol)
            if timeframe not in self._candles[symbol]:
                return
            if self._candles[symbol][timeframe]:
                return
            for c in candles:
                self._candles[symbol][timeframe].append(c)
            self.logger.info(
                f"Seeded {len(candles)} historical {timeframe} candles for {symbol}"
            )

    def get_candles(
        self,
        symbol: str,
        timeframe: str,
        count: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Get candles as pandas DataFrame.
        Includes current incomplete candle if available.
        """
        with self._lock:
            if symbol not in self._candles:
                return pd.DataFrame()

            if timeframe not in self._candles[symbol]:
                return pd.DataFrame()

            # Get completed candles
            candles = list(self._candles[symbol][timeframe])

            # Include current incomplete candle
            current = self._current_candles[symbol][timeframe]
            if current:
                candles = candles + [current]

            if count:
                candles = candles[-count:]

            if not candles:
                return pd.DataFrame()

            df = pd.DataFrame([c.to_dict() for c in candles])
            df['datetime'] = pd.to_datetime(df['epoch'], unit='s', utc=True)
            df.set_index('datetime', inplace=True)

            return df

    def get_latest_candle(self, symbol: str, timeframe: str) -> Optional[Candle]:
        """Get the most recent candle (including incomplete)"""
        with self._lock:
            if symbol in self._current_candles and timeframe in self._current_candles[symbol]:
                return self._current_candles[symbol][timeframe]
            return None

    def get_latest_price(self, symbol: str) -> Optional[float]:
        """Get latest tick price"""
        with self._lock:
            if symbol in self._tick_buffer and self._tick_buffer[symbol]:
                return self._tick_buffer[symbol][-1]["price"]
            return None

    def get_tick_history(self, symbol: str, count: int = 100) -> pd.DataFrame:
        """Get recent ticks as DataFrame"""
        with self._lock:
            if symbol not in self._tick_buffer:
                return pd.DataFrame()

            ticks = list(self._tick_buffer[symbol])[-count:]
            if not ticks:
                return pd.DataFrame()

            df = pd.DataFrame(ticks)
            df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
            df.set_index('datetime', inplace=True)
            return df

    def is_session_active(self, symbol: str = None, weekend_gate: bool = True) -> Dict[str, bool]:
        """
        Check which trading sessions are active.
        Returns dict with london, ny, asian, overlap_london_ny flags and
        market_open (forex weekend gate).
        """
        now = datetime.now(timezone.utc)

        # Crypto markets trade 24/7, so the weekend gate only applies to forex.
        apply_weekend_gate = weekend_gate and (symbol is None or not is_crypto_symbol(symbol))

        # Forex is closed on weekends (Sat 00:00 UTC through Sun < 22:00 UTC).
        # Without this gate the hour-based checks below would report e.g. the
        # Asian session as active on a Saturday morning.
        if apply_weekend_gate and not self._is_forex_open(now):
            return {
                "london": False,
                "ny": False,
                "asian": False,
                "overlap_london_ny": False,
                "market_open": False,
            }

        hour = now.hour

        # London: 08:00 - 17:00 UTC
        london = 8 <= hour < 17

        # NY: 13:00 - 22:00 UTC
        ny = 13 <= hour < 22

        # Asian: 00:00 - 08:00 UTC
        asian = 0 <= hour < 8

        return {
            "london": london,
            "ny": ny,
            "asian": asian,
            "overlap_london_ny": london and ny,  # Best liquidity
            "market_open": True,
        }

    @staticmethod
    def _is_forex_open(now: datetime) -> bool:
        """Forex market hours: open Sunday 22:00 UTC through Friday 22:00 UTC."""
        weekday = now.weekday()  # Monday=0 ... Sunday=6
        if weekday == 5:  # Saturday: fully closed
            return False
        if weekday == 6:  # Sunday: opens 22:00 UTC
            return now.hour >= 22
        if weekday == 4:  # Friday: closes 22:00 UTC
            return now.hour < 22
        return True

    def get_spread(self, symbol: str) -> Optional[float]:
        """Get current spread from latest tick"""
        with self._lock:
            if symbol in self._tick_buffer and self._tick_buffer[symbol]:
                latest = self._tick_buffer[symbol][-1]
                if latest.get("bid") and latest.get("ask"):
                    return latest["ask"] - latest["bid"]
            return None

    def get_stats(self) -> Dict:
        """Get engine statistics"""
        with self._lock:
            stats = {
                "symbols": list(self._candles.keys()),
                "timeframes": self.timeframes,
                "tick_buffer_sizes": {
                    s: len(buf) for s, buf in self._tick_buffer.items()
                },
                "candle_counts": {
                    s: {tf: len(candles) for tf, candles in tfs.items()}
                    for s, tfs in self._candles.items()
                }
            }
            return stats
