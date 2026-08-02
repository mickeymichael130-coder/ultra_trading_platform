"""
MarketAdvisor - AI-style research layer.

Reads a MarketSnapshot and produces a structured recommendation:
- market regime (trend direction + volatility)
- momentum state (MACD histogram + ADX)
- risk appetite (RSI positioning)
- action + confidence + human-readable rationale

Pure analysis: no side effects, no broker, no database.
"""
from dataclasses import dataclass, field
from typing import List, Optional

from ..indicators.technical import MarketSnapshot


@dataclass
class AdvisorRecommendation:
    """Research output from the MarketAdvisor."""
    action: str                      # "trade_buy" | "trade_sell" | "observe"
    regime: str
    volatility: str
    momentum: str
    risk_appetite: str
    confidence: float                # 0.0 - 1.0
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "regime": self.regime,
            "volatility": self.volatility,
            "momentum": self.momentum,
            "risk_appetite": self.risk_appetite,
            "confidence": round(self.confidence, 3),
            "reasons": list(self.reasons),
        }


class MarketAdvisor:
    """Synthesises indicator state into a researched recommendation."""

    def __init__(self, min_adx: float = 20.0, rsi_overbought: float = 70.0, rsi_oversold: float = 30.0):
        self.min_adx = min_adx
        self.rsi_overbought = rsi_overbought
        self.rsi_oversold = rsi_oversold

    # === Public API ===

    def advise(self, snapshot: MarketSnapshot) -> AdvisorRecommendation:
        reasons: List[str] = []

        regime = snapshot.trend_direction if snapshot.trend_direction else "neutral"
        volatility = snapshot.volatility_regime or "normal"

        # Momentum from MACD histogram + ADX trend strength.
        momentum, momentum_reason = self._momentum(snapshot)
        if momentum_reason:
            reasons.append(momentum_reason)

        # Risk appetite from RSI positioning.
        appetite, appetite_reason = self._risk_appetite(snapshot)
        if appetite_reason:
            reasons.append(appetite_reason)

        confidence = self._confidence(snapshot)

        action = self._action(snapshot, momentum, appetite, reasons)

        return AdvisorRecommendation(
            action=action,
            regime=regime,
            volatility=volatility,
            momentum=momentum,
            risk_appetite=appetite,
            confidence=confidence,
            reasons=reasons,
        )

    # === Helpers ===

    def _momentum(self, snapshot: MarketSnapshot) -> tuple:
        """Momentum from MACD histogram sign and ADX strength."""
        if snapshot.macd_histogram is None or snapshot.adx is None:
            return "unknown", "insufficient momentum data"

        if snapshot.adx >= self.min_adx:
            if snapshot.macd_histogram > 0:
                return "bullish", f"MACD positive & ADX {snapshot.adx:.0f} (strong trend)"
            return "bearish", f"MACD negative & ADX {snapshot.adx:.0f} (strong trend)"
        return "flat", f"ADX {snapshot.adx:.0f} below {self.min_adx:.0f} (no strong trend)"

    def _risk_appetite(self, snapshot: MarketSnapshot) -> tuple:
        """RSI positioning as a risk gauge."""
        rsi = snapshot.rsi
        if rsi is None:
            return "unknown", "insufficient RSI data"
        if rsi >= self.rsi_overbought:
            return "low", f"RSI {rsi:.0f} overbought (fade risk)"
        if rsi <= self.rsi_oversold:
            return "low", f"RSI {rsi:.0f} oversold (snap-back risk)"
        if self.rsi_overbought - 10 <= rsi < self.rsi_overbought:
            return "medium", f"RSI {rsi:.0f} approaching overbought"
        return "high", f"RSI {rsi:.0f} in neutral zone"

    def _confidence(self, snapshot: MarketSnapshot) -> float:
        """Weighted research confidence (0..1)."""
        score = 0.5
        if snapshot.adx is not None:
            # ADX in [0, 100]; reward strong trends, cap contribution.
            score += max(-0.2, min(0.2, (snapshot.adx - self.min_adx) / 100.0))
        if snapshot.rsi is not None:
            # Reward RSI away from extremes.
            distance = abs(50.0 - snapshot.rsi)
            score += 0.1 if distance < 20 else (-0.1 if distance > 35 else 0.0)
        if snapshot.atr_pips:
            # Penalise extreme volatility (whipsaw risk).
            if snapshot.volatility_regime == "high":
                score -= 0.1
        return max(0.05, min(0.95, score))

    def _action(self, snapshot: MarketSnapshot, momentum: str, appetite: str, reasons: List[str]) -> str:
        regime = snapshot.trend_direction or "neutral"

        if regime == "bullish" and momentum == "bullish" and appetite != "low":
            reasons.append("aligned bullish regime, momentum and appetite")
            return "trade_buy"
        if regime == "bearish" and momentum == "bearish" and appetite != "low":
            reasons.append("aligned bearish regime, momentum and appetite")
            return "trade_sell"

        conflict = []
        if regime in ("bullish", "bearish") and momentum in ("bullish", "bearish") and regime != momentum:
            conflict.append("trend and momentum disagree")
        if appetite == "low":
            conflict.append("RSI at extreme")
        if conflict:
            reasons.append("conflicting signals: " + "; ".join(conflict))
        return "observe"
