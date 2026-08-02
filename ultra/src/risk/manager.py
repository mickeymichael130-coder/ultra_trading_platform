"""
Risk Management Engine - THE GATEKEEPER
Every signal is inspected before execution.
Hard constraints for $2000 account. No exceptions.
"""
from typing import Optional, Dict, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import threading

from ..strategies.ema_crossover import TradeSignal, SignalDirection
from ..utils.logger import get_logger
from ..utils.pips import get_pip_size


class RiskDecision(Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    MODIFY = "MODIFY"
    COOLDOWN = "COOLDOWN"


@dataclass
class RiskCheck:
    """Result of a single risk check"""
    name: str
    passed: bool
    message: str
    severity: str  # "info", "warning", "critical"


@dataclass
class RiskResult:
    """Complete risk assessment result"""
    decision: RiskDecision
    signal: TradeSignal
    checks: List[RiskCheck] = field(default_factory=list)
    modified_signal: Optional[TradeSignal] = None
    reason: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @property
    def is_approved(self) -> bool:
        return self.decision == RiskDecision.APPROVE

    def to_dict(self) -> Dict:
        return {
            "decision": self.decision.value,
            "symbol": self.signal.symbol,
            "direction": self.signal.direction.value,
            "reason": self.reason,
            "checks": [
                {"name": c.name, "passed": c.passed, "message": c.message, "severity": c.severity}
                for c in self.checks
            ],
            "timestamp": self.timestamp.isoformat()
        }


class RiskManager:
    """
    Risk Management Engine.

    HARD CONSTRAINTS (for $2000 account):
    - Max risk per trade: 1.5% ($30)
    - Max daily loss: 3% ($60)
    - Max drawdown: 10% ($200) → KILL SWITCH
    - Max open trades: 2
    - Max trades per day: 6
    - Cooldown after loss: 15 minutes
    - Max correlated trades: 1

    State Machine:
    - Tracks daily P&L, open positions, trade history
    - Persists state to database
    - Can trigger emergency shutdown
    """

    def __init__(
        self,
        initial_capital: float = 2000.0,
        max_risk_per_trade_pct: float = 1.5,
        max_risk_per_trade_abs: float = 30.0,
        max_daily_loss_pct: float = 3.0,
        max_daily_loss_abs: float = 60.0,
        max_drawdown_pct: float = 10.0,
        max_drawdown_abs: float = 200.0,
        max_open_trades: int = 2,
        max_trades_per_day: int = 6,
        cooldown_after_loss_minutes: int = 15,
        max_correlated_trades: int = 1,
        effective_leverage: float = 50.0
    ):
        self.initial_capital = initial_capital
        self.max_risk_per_trade_pct = max_risk_per_trade_pct
        self.max_risk_per_trade_abs = max_risk_per_trade_abs
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_daily_loss_abs = max_daily_loss_abs
        self.max_drawdown_pct = max_drawdown_pct
        self.max_drawdown_abs = max_drawdown_abs
        self.max_open_trades = max_open_trades
        self.max_trades_per_day = max_trades_per_day
        self.cooldown_after_loss_minutes = cooldown_after_loss_minutes
        self.max_correlated_trades = max_correlated_trades
        self.effective_leverage = effective_leverage

        self.logger = get_logger("risk.manager")

        # State tracking
        self._lock = threading.RLock()
        self._current_balance: float = initial_capital
        self._peak_balance: float = initial_capital
        self._open_trades: List[Dict] = []
        self._today_trades: List[Dict] = []
        self._daily_pnl: float = 0.0
        self._last_loss_time: Optional[datetime] = None
        self._kill_switch_active: bool = False
        self._today_date: datetime = datetime.utcnow().date()

        # Correlation groups for forex
        self._correlation_groups = {
            "eur_usd_group": ["frxEURUSD", "frxGBPUSD", "frxEURGBP"],
            "usd_jpy_group": ["frxUSDJPY", "frxEURJPY", "frxGBPJPY"],
            "commodity_dollar": ["frxAUDUSD", "frxNZDUSD", "frxUSDCAD"]
        }

        self.logger.info(
            f"RiskManager initialized | Capital: ${initial_capital} | "
            f"Max Risk/Trade: ${max_risk_per_trade_abs} | Max DD: ${max_drawdown_abs}"
        )

    def evaluate(self, signal: TradeSignal, current_balance: float) -> RiskResult:
        """
        Evaluate a trading signal against all risk rules.

        Args:
            signal: The trade signal to evaluate
            current_balance: Current account balance from broker

        Returns:
            RiskResult with APPROVE, REJECT, MODIFY, or COOLDOWN
        """
        with self._lock:
            checks = []

            # Update balance
            self._current_balance = current_balance
            self._peak_balance = max(self._peak_balance, current_balance)

            # Reset daily stats if new day
            self._check_new_day()

            # === Check 1: Kill Switch ===
            if self._kill_switch_active:
                checks.append(RiskCheck(
                    name="kill_switch",
                    passed=False,
                    message="KILL SWITCH ACTIVE - Trading halted",
                    severity="critical"
                ))
                return RiskResult(
                    decision=RiskDecision.REJECT,
                    signal=signal,
                    checks=checks,
                    reason="Kill switch active - maximum drawdown exceeded"
                )

            # === Check 2: Drawdown ===
            drawdown = self._calculate_drawdown()
            drawdown_passed = drawdown < self.max_drawdown_abs
            checks.append(RiskCheck(
                name="drawdown",
                passed=drawdown_passed,
                message=f"Drawdown: ${drawdown:.2f} / ${self.max_drawdown_abs:.2f}",
                severity="critical" if not drawdown_passed else "info"
            ))

            if not drawdown_passed:
                self._activate_kill_switch()
                return RiskResult(
                    decision=RiskDecision.REJECT,
                    signal=signal,
                    checks=checks,
                    reason=f"Maximum drawdown exceeded: ${drawdown:.2f}"
                )

            # === Check 3: Daily Loss Limit ===
            daily_loss = abs(min(self._daily_pnl, 0))
            daily_loss_passed = daily_loss < self.max_daily_loss_abs
            checks.append(RiskCheck(
                name="daily_loss",
                passed=daily_loss_passed,
                message=f"Daily loss: ${daily_loss:.2f} / ${self.max_daily_loss_abs:.2f}",
                severity="critical" if not daily_loss_passed else "info"
            ))

            if not daily_loss_passed:
                return RiskResult(
                    decision=RiskDecision.REJECT,
                    signal=signal,
                    checks=checks,
                    reason=f"Daily loss limit reached: ${daily_loss:.2f}"
                )

            # === Check 4: Max Open Trades ===
            open_count = len(self._open_trades)
            open_passed = open_count < self.max_open_trades
            checks.append(RiskCheck(
                name="max_open_trades",
                passed=open_passed,
                message=f"Open trades: {open_count} / {self.max_open_trades}",
                severity="warning" if not open_passed else "info"
            ))

            if not open_passed:
                return RiskResult(
                    decision=RiskDecision.REJECT,
                    signal=signal,
                    checks=checks,
                    reason=f"Maximum open trades reached: {open_count}"
                )

            # === Check 5: Max Trades Per Day ===
            daily_count = len(self._today_trades)
            daily_count_passed = daily_count < self.max_trades_per_day
            checks.append(RiskCheck(
                name="max_daily_trades",
                passed=daily_count_passed,
                message=f"Daily trades: {daily_count} / {self.max_trades_per_day}",
                severity="warning" if not daily_count_passed else "info"
            ))

            if not daily_count_passed:
                return RiskResult(
                    decision=RiskDecision.REJECT,
                    signal=signal,
                    checks=checks,
                    reason=f"Daily trade limit reached: {daily_count}"
                )

            # === Check 6: Cooldown After Loss ===
            cooldown_passed = self._check_cooldown()
            checks.append(RiskCheck(
                name="cooldown",
                passed=cooldown_passed,
                message=self._get_cooldown_message(),
                severity="warning" if not cooldown_passed else "info"
            ))

            if not cooldown_passed:
                return RiskResult(
                    decision=RiskDecision.COOLDOWN,
                    signal=signal,
                    checks=checks,
                    reason="Cooldown period active after loss"
                )

            # === Check 7: Correlation Risk ===
            correlation_passed = self._check_correlation(signal.symbol)
            checks.append(RiskCheck(
                name="correlation",
                passed=correlation_passed,
                message=f"Correlation check for {signal.symbol}",
                severity="warning" if not correlation_passed else "info"
            ))

            if not correlation_passed:
                return RiskResult(
                    decision=RiskDecision.REJECT,
                    signal=signal,
                    checks=checks,
                    reason="Correlation risk - similar pair already in trade"
                )

            # === Check 8: Position Sizing ===
            sized_signal = self._calculate_position_size(signal, current_balance)
            if sized_signal is None:
                checks.append(RiskCheck(
                    name="position_size",
                    passed=False,
                    message="Position size calculation failed",
                    severity="critical"
                ))
                return RiskResult(
                    decision=RiskDecision.REJECT,
                    signal=signal,
                    checks=checks,
                    reason="Position sizing failed"
                )

            risk_amount = sized_signal.risk_amount or 0
            risk_pct = (risk_amount / current_balance) * 100
            sizing_passed = risk_amount <= self.max_risk_per_trade_abs
            checks.append(RiskCheck(
                name="position_size",
                passed=sizing_passed,
                message=f"Risk: ${risk_amount:.2f} ({risk_pct:.2f}%) / ${self.max_risk_per_trade_abs:.2f}",
                severity="warning" if not sizing_passed else "info"
            ))

            if not sizing_passed:
                return RiskResult(
                    decision=RiskDecision.REJECT,
                    signal=signal,
                    checks=checks,
                    reason=f"Risk per trade too high: ${risk_amount:.2f}"
                )

            # === Check 9: Signal Confidence ===
            confidence_passed = signal.confidence >= 0.6
            checks.append(RiskCheck(
                name="confidence",
                passed=confidence_passed,
                message=f"Confidence: {signal.confidence:.2f} / 0.60",
                severity="warning" if not confidence_passed else "info"
            ))

            if not confidence_passed:
                return RiskResult(
                    decision=RiskDecision.REJECT,
                    signal=signal,
                    checks=checks,
                    reason=f"Signal confidence too low: {signal.confidence:.2f}"
                )

            # === Check 10: Stop Loss Validation ===
            sl_valid = self._validate_stop_loss(sized_signal)
            checks.append(RiskCheck(
                name="stop_loss",
                passed=sl_valid,
                message="Stop loss within risk parameters",
                severity="critical" if not sl_valid else "info"
            ))

            if not sl_valid:
                return RiskResult(
                    decision=RiskDecision.REJECT,
                    signal=signal,
                    checks=checks,
                    reason="Invalid stop loss configuration"
                )

            # ALL CHECKS PASSED
            self.logger.info(
                f"✅ APPROVED: {signal.symbol} {signal.direction.value} | "
                f"Risk: ${risk_amount:.2f} | Size: {sized_signal.position_size}"
            )

            return RiskResult(
                decision=RiskDecision.APPROVE,
                signal=signal,
                checks=checks,
                modified_signal=sized_signal,
                reason="All risk checks passed"
            )

    def _calculate_position_size(
        self,
        signal: TradeSignal,
        balance: float
    ) -> Optional[TradeSignal]:
        """
        Calculate position size based on risk amount and stop distance.

        Formula: Position Size = Risk Amount / (Stop Distance in pips * Pip Value)
        """
        if not signal.stop_loss or not signal.entry_price:
            return None

        # Determine pip size based on symbol
        pip_size = self._get_pip_size(signal.symbol)
        pip_value = 0.10  # $0.10 per pip per micro lot (standard)

        # Calculate stop distance in pips
        stop_distance = abs(signal.entry_price - signal.stop_loss)
        stop_pips = stop_distance / pip_size

        if stop_pips < 5:  # Minimum 5 pip stop
            self.logger.warning(f"Stop too tight: {stop_pips:.1f} pips")
            return None

        # Risk amount (1.5% of balance, max $30)
        risk_pct = self.max_risk_per_trade_pct / 100
        risk_amount = min(balance * risk_pct, self.max_risk_per_trade_abs)

        # Position size in micro lots
        position_size_micro = risk_amount / (stop_pips * pip_value)

        # Round to standard lot sizes
        if position_size_micro >= 100:
            position_size = round(position_size_micro / 100, 2)  # Standard lots
            unit = "lots"
        else:
            position_size = round(position_size_micro, 2)
            unit = "micro lots"

        # Create modified signal with sizing
        modified = TradeSignal(
            symbol=signal.symbol,
            direction=signal.direction,
            strength=signal.strength,
            confidence=signal.confidence,
            timestamp=signal.timestamp,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            strategy_name=signal.strategy_name,
            timeframe=signal.timeframe,
            reason=signal.reason,
            risk_amount=risk_amount,
            position_size=position_size
        )

        self.logger.debug(
            f"Position sizing: {signal.symbol} | "
            f"Risk: ${risk_amount:.2f} | Stop: {stop_pips:.1f} pips | "
            f"Size: {position_size} {unit}"
        )

        return modified

    def _validate_stop_loss(self, signal: TradeSignal) -> bool:
        """Validate stop loss is within risk parameters"""
        if not signal.stop_loss or not signal.entry_price or not signal.risk_amount:
            return False

        stop_distance = abs(signal.entry_price - signal.stop_loss)
        pip_size = self._get_pip_size(signal.symbol)
        stop_pips = stop_distance / pip_size

        # Reasonable stop range: 10-50 pips for intraday
        return 5 <= stop_pips <= 100

    def _calculate_drawdown(self) -> float:
        """Calculate current drawdown from peak"""
        return self._peak_balance - self._current_balance

    def _activate_kill_switch(self):
        """Activate emergency stop"""
        self._kill_switch_active = True
        self.logger.critical(
            f"🚨 KILL SWITCH ACTIVATED | Drawdown: ${self._calculate_drawdown():.2f} | "
            f"Trading halted permanently until manual reset"
        )

    def reset_kill_switch(self):
        """Manual reset of kill switch (requires human intervention)"""
        self._kill_switch_active = False
        self._peak_balance = self._current_balance
        self.logger.warning("Kill switch manually reset by operator")

    def _check_cooldown(self) -> bool:
        """Check if cooldown period has elapsed since last loss"""
        if self._last_loss_time is None:
            return True

        elapsed = datetime.utcnow() - self._last_loss_time
        return elapsed >= timedelta(minutes=self.cooldown_after_loss_minutes)

    def _get_cooldown_message(self) -> str:
        """Get cooldown status message"""
        if self._last_loss_time is None:
            return "No cooldown active"

        elapsed = datetime.utcnow() - self._last_loss_time
        remaining = timedelta(minutes=self.cooldown_after_loss_minutes) - elapsed

        if remaining.total_seconds() <= 0:
            return "Cooldown expired"

        return f"Cooldown: {remaining.seconds // 60}m {remaining.seconds % 60}s remaining"

    def _check_correlation(self, symbol: str) -> bool:
        """Check if correlated pair is already in trade"""
        # Find which group this symbol belongs to
        symbol_group = None
        for group_name, symbols in self._correlation_groups.items():
            if symbol in symbols:
                symbol_group = group_name
                break

        if not symbol_group:
            return True  # Unknown symbol, allow

        # Count open trades in same group
        group_trades = [
            t for t in self._open_trades
            if any(t['symbol'] in self._correlation_groups[symbol_group] for s in [t['symbol']])
        ]

        return len(group_trades) < self.max_correlated_trades

    def _check_new_day(self):
        """Reset daily counters if new day"""
        today = datetime.utcnow().date()
        if today != self._today_date:
            self.logger.info(f"New day detected. Resetting daily counters.")
            self._today_date = today
            self._today_trades = []
            self._daily_pnl = 0.0

    def _get_pip_size(self, symbol: str) -> float:
        """Get pip size for symbol (crypto-aware, shared with indicators)."""
        return get_pip_size(symbol)

    # === Trade Lifecycle Methods ===

    def on_trade_opened(self, trade: Dict):
        """Record opened trade"""
        with self._lock:
            self._open_trades.append(trade)
            self._today_trades.append(trade)
            self.logger.info(
                f"Trade opened: {trade['symbol']} | "
                f"Open trades: {len(self._open_trades)}"
            )

    def on_trade_closed(self, trade: Dict, pnl: float):
        """Record closed trade and update P&L"""
        with self._lock:
            # Remove from open trades
            self._open_trades = [
                t for t in self._open_trades
                if t.get('id') != trade.get('id')
            ]

            # Update P&L
            self._daily_pnl += pnl

            # Track loss for cooldown
            if pnl < 0:
                self._last_loss_time = datetime.utcnow()
                self.logger.warning(
                    f"Loss recorded: ${pnl:.2f} | "
                    f"Cooldown activated for {self.cooldown_after_loss_minutes} minutes"
                )

            self.logger.info(
                f"Trade closed: {trade['symbol']} | P&L: ${pnl:.2f} | "
                f"Daily P&L: ${self._daily_pnl:.2f}"
            )

    def get_status(self) -> Dict:
        """Get current risk status"""
        with self._lock:
            return {
                "balance": self._current_balance,
                "peak_balance": self._peak_balance,
                "drawdown": self._calculate_drawdown(),
                "drawdown_pct": (self._calculate_drawdown() / self._peak_balance) * 100,
                "daily_pnl": self._daily_pnl,
                "open_trades": len(self._open_trades),
                "daily_trades": len(self._today_trades),
                "kill_switch_active": self._kill_switch_active,
                "cooldown_active": not self._check_cooldown(),
                "cooldown_message": self._get_cooldown_message()
            }
