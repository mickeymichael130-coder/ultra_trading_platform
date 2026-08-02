"""
EMA Crossover Strategy
Generates BUY/SELL/HOLD signals based on EMA alignment + RSI filter.
No broker communication. Pure signal generation.
"""
from typing import Optional, Dict
import pandas as pd

from ..core.domain import Signal as TradeSignal, SignalDirection, SignalStrength
from ..indicators.technical import MarketSnapshot
from ..utils.logger import get_logger


class EMACrossoverStrategy:
    """
    EMA Crossover with RSI Filter Strategy.

    Rules:
    - BUY: Fast EMA crosses above Slow EMA, RSI not overbought, bullish trend
    - SELL: Fast EMA crosses below Slow EMA, RSI not oversold, bearish trend
    - ADX > 25 required for trend confirmation
    - Avoid Asian session
    - Minimum ATR filter (avoid low volatility)
    """

    def __init__(
        self,
        min_atr_pips: float = 5.0,
        min_confidence: float = 0.6,
        rsi_overbought: float = 70.0,
        rsi_oversold: float = 30.0,
        adx_threshold: float = 25.0,
        trade_london: bool = True,
        trade_ny: bool = True,
        trade_asian: bool = False
    ):
        self.min_atr_pips = min_atr_pips
        self.min_confidence = min_confidence
        self.rsi_overbought = rsi_overbought
        self.rsi_oversold = rsi_oversold
        self.adx_threshold = adx_threshold
        self.trade_london = trade_london
        self.trade_ny = trade_ny
        self.trade_asian = trade_asian

        self.logger = get_logger("strategy.ema_crossover")
        self.name = "EMA_Crossover_RSI"

        # Track previous EMA state for crossover detection
        self._previous_states: Dict[str, Dict] = {}

    def generate_signal(
        self,
        snapshot: MarketSnapshot,
        session_info: Dict[str, bool],
        previous_snapshot: Optional[MarketSnapshot] = None
    ) -> TradeSignal:
        """
        Generate trading signal from market snapshot.

        Args:
            snapshot: Current market snapshot with indicators
            session_info: Active trading sessions
            previous_snapshot: Previous snapshot for crossover detection

        Returns:
            TradeSignal with direction and parameters
        """
        symbol = snapshot.symbol
        tf = snapshot.timeframe

        # Default: HOLD
        signal = TradeSignal(
            symbol=symbol,
            direction=SignalDirection.HOLD,
            strength=SignalStrength.WEAK,
            confidence=0.0,
            timestamp=snapshot.timestamp,
            strategy_name=self.name,
            timeframe=tf
        )

        # === Session Filter ===
        if not self._check_session(session_info):
            signal.reason = "Outside trading session"
            return signal

        # === Data Quality Check ===
        if not self._validate_snapshot(snapshot):
            signal.reason = "Insufficient indicator data"
            return signal

        # === ATR Filter ===
        if snapshot.atr_pips and snapshot.atr_pips < self.min_atr_pips:
            signal.reason = f"ATR too low ({snapshot.atr_pips:.1f} < {self.min_atr_pips})"
            return signal

        # === Trend Filter ===
        if snapshot.trend_direction == "neutral":
            signal.reason = "No clear trend"
            return signal

        # === ADX Filter ===
        if snapshot.adx and snapshot.adx < self.adx_threshold:
            signal.reason = f"ADX too weak ({snapshot.adx:.1f} < {self.adx_threshold})"
            return signal

        # === EMA Crossover Detection ===
        crossover = self._detect_crossover(snapshot, previous_snapshot, symbol)

        if crossover == "bullish_cross":
            # Check RSI filter
            if snapshot.rsi and snapshot.rsi > self.rsi_overbought:
                signal.reason = f"RSI overbought ({snapshot.rsi:.1f})"
                return signal

            # Check trend alignment
            if snapshot.trend_direction != "bullish":
                signal.reason = "Bullish cross but trend not bullish"
                return signal

            # Generate BUY signal
            signal.direction = SignalDirection.BUY
            signal.strength = self._calculate_strength(snapshot)
            signal.confidence = self._calculate_confidence(snapshot, "buy")
            signal.reason = f"EMA crossover bullish | RSI:{snapshot.rsi:.1f} | ADX:{snapshot.adx:.1f}"

        elif crossover == "bearish_cross":
            # Check RSI filter
            if snapshot.rsi and snapshot.rsi < self.rsi_oversold:
                signal.reason = f"RSI oversold ({snapshot.rsi:.1f})"
                return signal

            # Check trend alignment
            if snapshot.trend_direction != "bearish":
                signal.reason = "Bearish cross but trend not bearish"
                return signal

            # Generate SELL signal
            signal.direction = SignalDirection.SELL
            signal.strength = self._calculate_strength(snapshot)
            signal.confidence = self._calculate_confidence(snapshot, "sell")
            signal.reason = f"EMA crossover bearish | RSI:{snapshot.rsi:.1f} | ADX:{snapshot.adx:.1f}"

        else:
            signal.reason = f"No crossover detected ({crossover})"

        # Calculate entry/exit if valid signal
        if signal.is_valid():
            signal.entry_price = snapshot.current_price
            signal.atr = snapshot.atr
            signal.stop_loss = self._calculate_stop_loss(snapshot, signal.direction)
            signal.take_profit = self._calculate_take_profit(snapshot, signal.direction)

        self.logger.debug(
            f"Signal: {symbol} {tf} | {signal.direction.value} | "
            f"Confidence: {signal.confidence:.2f} | {signal.reason}"
        )

        return signal

    def _check_session(self, session_info: Dict[str, bool]) -> bool:
        """Check if current session allows trading"""
        if session_info.get("overlap_london_ny"):
            return True  # Best liquidity
        if self.trade_london and session_info.get("london"):
            return True
        if self.trade_ny and session_info.get("ny"):
            return True
        if self.trade_asian and session_info.get("asian"):
            return True
        return False

    def _validate_snapshot(self, snapshot: MarketSnapshot) -> bool:
        """Ensure all required indicators are present"""
        required = [
            snapshot.ema_fast, snapshot.ema_slow, snapshot.ema_trend,
            snapshot.rsi, snapshot.atr, snapshot.adx,
            snapshot.macd_line, snapshot.macd_signal
        ]
        return all(v is not None and not pd.isna(v) for v in required)

    def _detect_crossover(
        self,
        snapshot: MarketSnapshot,
        previous: Optional[MarketSnapshot],
        symbol: str
    ) -> str:
        """
        Detect EMA crossover.
        Returns: "bullish_cross", "bearish_cross", "no_cross", "already_aligned"
        """
        current_fast = snapshot.ema_fast
        current_slow = snapshot.ema_slow

        if previous is None:
            # First run - check current alignment only
            if current_fast > current_slow:
                return "already_bullish"
            elif current_fast < current_slow:
                return "already_bearish"
            return "no_cross"

        prev_fast = previous.ema_fast
        prev_slow = previous.ema_slow

        # Bullish cross: fast was below, now above
        if prev_fast <= prev_slow and current_fast > current_slow:
            return "bullish_cross"

        # Bearish cross: fast was above, now below
        if prev_fast >= prev_slow and current_fast < current_slow:
            return "bearish_cross"

        # Already aligned
        if current_fast > current_slow:
            return "already_bullish"
        elif current_fast < current_slow:
            return "already_bearish"

        return "no_cross"

    def _calculate_strength(self, snapshot: MarketSnapshot) -> SignalStrength:
        """Determine signal strength based on indicator alignment"""
        score = 0

        # ADX strength
        if snapshot.adx and snapshot.adx > 30:
            score += 2
        elif snapshot.adx and snapshot.adx > 25:
            score += 1

        # Trend strength
        if snapshot.trend_direction == "bullish":
            if snapshot.current_price > snapshot.ema_trend:
                score += 1
        elif snapshot.trend_direction == "bearish":
            if snapshot.current_price < snapshot.ema_trend:
                score += 1

        # MACD confirmation
        if snapshot.macd_histogram and abs(snapshot.macd_histogram) > 0.0001:
            score += 1

        # Volume (if available)
        if snapshot.volume and snapshot.volume > 100:
            score += 1

        if score >= 4:
            return SignalStrength.STRONG
        elif score >= 2:
            return SignalStrength.MODERATE
        return SignalStrength.WEAK

    def _calculate_confidence(
        self,
        snapshot: MarketSnapshot,
        direction: str
    ) -> float:
        """Calculate confidence score (0.0 - 1.0)"""
        confidence = 0.5  # Base

        # ADX contribution (0-0.2)
        if snapshot.adx:
            confidence += min((snapshot.adx - 25) / 50, 0.2)

        # RSI distance from extremes (0-0.15)
        if snapshot.rsi:
            if direction == "buy":
                confidence += min((70 - snapshot.rsi) / 100, 0.15)
            else:
                confidence += min((snapshot.rsi - 30) / 100, 0.15)

        # Trend alignment (0-0.15)
        if snapshot.trend_direction == "bullish" and direction == "buy":
            confidence += 0.15
        elif snapshot.trend_direction == "bearish" and direction == "sell":
            confidence += 0.15

        # MACD histogram (0-0.1)
        if snapshot.macd_histogram:
            if direction == "buy" and snapshot.macd_histogram > 0:
                confidence += 0.1
            elif direction == "sell" and snapshot.macd_histogram < 0:
                confidence += 0.1

        return min(confidence, 1.0)

    def _calculate_stop_loss(
        self,
        snapshot: MarketSnapshot,
        direction: SignalDirection
    ) -> float:
        """Calculate stop loss based on ATR"""
        atr = snapshot.atr or 0.0010  # Default 10 pips
        multiplier = 1.5

        if direction == SignalDirection.BUY:
            return snapshot.current_price - (atr * multiplier)
        else:
            return snapshot.current_price + (atr * multiplier)

    def _calculate_take_profit(
        self,
        snapshot: MarketSnapshot,
        direction: SignalDirection
    ) -> float:
        """Calculate take profit based on ATR (2.5x)"""
        atr = snapshot.atr or 0.0010
        multiplier = 2.5

        if direction == SignalDirection.BUY:
            return snapshot.current_price + (atr * multiplier)
        else:
            return snapshot.current_price - (atr * multiplier)
