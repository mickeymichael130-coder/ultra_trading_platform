"""
SignalEnhancer - AI Research Lab calibration layer.

Takes a strategy TradeSignal and improves it using:
1. Advisor agreement (MarketAdvisor recommendation direction).
2. Higher-timeframe trend confirmation.

Returns an enhanced copy of the signal with adjusted confidence, strength
and an AI research note. Never changes direction or risk parameters; it
only calibrates confidence so downstream risk sizing is more informed.
"""
from copy import deepcopy
from typing import Optional

from ..indicators.technical import MarketSnapshot
from ..strategies.ema_crossover import TradeSignal, SignalDirection, SignalStrength
from .advisor import MarketAdvisor


class SignalEnhancer:
    """Calibrates a signal with research-grade analysis."""

    def __init__(
        self,
        advisor: Optional[MarketAdvisor] = None,
        confidence_boost: float = 0.08,
        confidence_penalty: float = 0.12,
    ):
        self.advisor = advisor or MarketAdvisor()
        self.confidence_boost = confidence_boost
        self.confidence_penalty = confidence_penalty

    def enhance(
        self,
        signal: TradeSignal,
        snapshot: MarketSnapshot,
        higher_tf_snapshot: Optional[MarketSnapshot] = None,
    ) -> TradeSignal:
        """Return a deep copy of the signal with calibrated confidence."""
        enhanced = deepcopy(signal)
        if enhanced.direction == SignalDirection.HOLD:
            return enhanced

        notes = []
        advisor = self.advisor.advise(snapshot)

        # 1. Advisor agreement / disagreement.
        advised_direction = self._advisor_direction(advisor.action)
        if advised_direction == enhanced.direction:
            enhanced.confidence = min(1.0, enhanced.confidence + self.confidence_boost)
            notes.append("advisor confirms direction")
        elif advised_direction is not None:
            enhanced.confidence = max(0.0, enhanced.confidence - self.confidence_penalty)
            notes.append("advisor disagrees with direction")

        # 2. Higher-timeframe confirmation.
        if higher_tf_snapshot is not None:
            ht_trend = higher_tf_snapshot.trend_direction or "neutral"
            signal_side = "bullish" if enhanced.direction == SignalDirection.BUY else "bearish"
            if ht_trend == signal_side:
                enhanced.confidence = min(1.0, enhanced.confidence + 0.05)
                notes.append(f"higher-timeframe ({ht_trend}) confirms")
            elif ht_trend != "neutral":
                enhanced.confidence = max(0.0, enhanced.confidence - 0.05)
                notes.append(f"higher-timeframe ({ht_trend}) conflicts")

        # 3. Refresh strength from calibrated confidence.
        enhanced.strength = self._strength_from_confidence(enhanced.confidence)

        # 4. Record the research note.
        prefix = f"AI: {advisor.regime} regime"
        if notes:
            prefix += " | " + "; ".join(notes)
        enhanced.reason = f"{prefix} | {enhanced.reason}" if enhanced.reason else prefix

        return enhanced

    def _advisor_direction(self, action: str) -> Optional[SignalDirection]:
        if action == "trade_buy":
            return SignalDirection.BUY
        if action == "trade_sell":
            return SignalDirection.SELL
        return None

    def _strength_from_confidence(self, confidence: float) -> SignalStrength:
        if confidence >= 0.75:
            return SignalStrength.STRONG
        if confidence >= 0.6:
            return SignalStrength.MODERATE
        return SignalStrength.WEAK
