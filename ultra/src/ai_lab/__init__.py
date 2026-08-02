"""
AI Research Lab (Phase 16 - optional)

Provides research-grade analysis on top of the indicator engine:
- MarketAdvisor: synthesises regime / momentum / risk appetite into an
  actionable recommendation with a confidence score and rationale.
- SignalEnhancer: adjusts a strategy signal using multi-timeframe and
  advisor agreement, producing a researched, calibrated signal.

Both modules are pure (no I/O, no broker access, no DB writes) so they can
run offline and be unit tested in isolation.
"""
from .advisor import MarketAdvisor, AdvisorRecommendation
from .signal_enhancer import SignalEnhancer

__all__ = ["MarketAdvisor", "AdvisorRecommendation", "SignalEnhancer"]
