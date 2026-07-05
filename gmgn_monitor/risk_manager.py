from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from .trade_signal import TradeSignal

__all__ = [
    "RiskLimits",
    "CircuitBreakerState",
    "RiskCheckResult",
    "RiskManager",
]


class RiskCheckResult(Enum):
    """Result of a pre-trade risk check."""

    ALLOW = "allow"
    BLOCK = "block"
    WARN = "warn"


@dataclass
class RiskLimits:
    """Configurable risk thresholds for the trading system."""

    daily_loss_limit_percent: float
    max_single_position_percent: float
    max_total_positions: int
    default_stop_loss_percent: float
    circuit_breaker_cooldown_seconds: int = 600
    kill_switch: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "daily_loss_limit_percent": self.daily_loss_limit_percent,
            "max_single_position_percent": self.max_single_position_percent,
            "max_total_positions": self.max_total_positions,
            "default_stop_loss_percent": self.default_stop_loss_percent,
            "circuit_breaker_cooldown_seconds": self.circuit_breaker_cooldown_seconds,
            "kill_switch": self.kill_switch,
        }


@dataclass
class CircuitBreakerState:
    """Tracks whether the circuit breaker is active and why."""

    triggered: bool = False
    triggered_at: datetime | None = None
    reason: str | None = None
    consecutive_failed_trades: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "triggered": self.triggered,
            "triggered_at": self.triggered_at.isoformat() if self.triggered_at else None,
            "reason": self.reason,
            "consecutive_failed_trades": self.consecutive_failed_trades,
        }


class RiskManager:
    """Real-time risk management and circuit-breaker system.

    Enforces daily loss limits, position-size caps, maximum open positions,
    a cooldown-based circuit breaker, and a manual kill switch.
    """

    def __init__(self, risk_limits: RiskLimits) -> None:
        self.risk_limits = risk_limits
        self.circuit_breaker = CircuitBreakerState()
        self._kill_switch_active = risk_limits.kill_switch
        self._kill_switch_reason: str | None = None
        self._daily_pnl_sol: float = 0.0

    # ------------------------------------------------------------------
    # Pre-trade checks
    # ------------------------------------------------------------------

    def check_trade(
        self,
        signal: TradeSignal,
        current_portfolio_value: float,
        open_positions: list[dict],
    ) -> RiskCheckResult:
        """Run all pre-trade risk checks.

        Returns ``ALLOW`` if the trade may proceed, ``BLOCK`` if it must not,
        or ``WARN`` if it is allowed but carries elevated risk.
        """
        if self.is_kill_switch_active():
            return RiskCheckResult.BLOCK

        if self.is_circuit_breaker_active():
            return RiskCheckResult.BLOCK

        if current_portfolio_value <= 0:
            return RiskCheckResult.BLOCK

        # Daily loss limit
        daily_pnl_percent = (
            (self._daily_pnl_sol / current_portfolio_value) * 100.0
            if current_portfolio_value > 0
            else 0.0
        )
        if self.check_daily_loss(daily_pnl_percent):
            self.trigger_circuit_breaker("daily loss limit exceeded")
            return RiskCheckResult.BLOCK

        # Consecutive failed trades
        if self.circuit_breaker.consecutive_failed_trades >= 3:
            self.trigger_circuit_breaker("consecutive failed trades >= 3")
            return RiskCheckResult.BLOCK

        # Position size
        if not self.check_position_size(signal.recommended_amount_sol, current_portfolio_value):
            return RiskCheckResult.BLOCK

        # Max positions
        if not self.check_max_positions(len(open_positions)):
            return RiskCheckResult.BLOCK

        # Elevated risk heuristics
        if signal.max_slippage_percent > 50 or signal.confidence_score < 30:
            return RiskCheckResult.WARN

        return RiskCheckResult.ALLOW

    def check_position_size(self, amount_sol: float, current_portfolio_value: float) -> bool:
        """Return ``True`` if the proposed position size is within limits."""
        if current_portfolio_value <= 0:
            return False
        position_percent = (amount_sol / current_portfolio_value) * 100.0
        return position_percent <= self.risk_limits.max_single_position_percent

    def check_daily_loss(self, daily_pnl_percent: float) -> bool:
        """Return ``True`` if the daily loss limit has been *exceeded*."""
        return daily_pnl_percent < -self.risk_limits.daily_loss_limit_percent

    def check_max_positions(self, open_count: int) -> bool:
        """Return ``True`` if we are still under the maximum allowed positions."""
        return open_count < self.risk_limits.max_total_positions

    # ------------------------------------------------------------------
    # Circuit breaker
    # ------------------------------------------------------------------

    def trigger_circuit_breaker(self, reason: str) -> None:
        """Activate the circuit breaker and record the trigger reason."""
        self.circuit_breaker.triggered = True
        self.circuit_breaker.triggered_at = datetime.utcnow()
        self.circuit_breaker.reason = reason

    def reset_circuit_breaker(self) -> None:
        """Manually reset the circuit breaker and its failure counter."""
        self.circuit_breaker.triggered = False
        self.circuit_breaker.triggered_at = None
        self.circuit_breaker.reason = None
        self.circuit_breaker.consecutive_failed_trades = 0

    def is_circuit_breaker_active(self) -> bool:
        """Return ``True`` if the breaker is triggered and still inside its cooldown window."""
        if not self.circuit_breaker.triggered:
            return False
        if self.circuit_breaker.triggered_at is None:
            return False
        cooldown = timedelta(seconds=self.risk_limits.circuit_breaker_cooldown_seconds)
        return datetime.utcnow() < self.circuit_breaker.triggered_at + cooldown

    # ------------------------------------------------------------------
    # Kill switch
    # ------------------------------------------------------------------

    def is_kill_switch_active(self) -> bool:
        """Return ``True`` if the emergency kill switch is engaged."""
        return self._kill_switch_active

    def activate_kill_switch(self, reason: str) -> None:
        """Engage the emergency kill switch; no new trades until manually reset."""
        self._kill_switch_active = True
        self._kill_switch_reason = reason

    def deactivate_kill_switch(self) -> None:
        """Disengage the emergency kill switch."""
        self._kill_switch_active = False
        self._kill_switch_reason = None

    # ------------------------------------------------------------------
    # P&L tracking
    # ------------------------------------------------------------------

    def update_daily_pnl(self, pnl_sol: float) -> None:
        """Accumulate running daily P&L (in SOL)."""
        self._daily_pnl_sol += pnl_sol

    # ------------------------------------------------------------------
    # Trade-outcome tracking (required for circuit-breaker logic)
    # ------------------------------------------------------------------

    def record_trade_result(self, success: bool) -> None:
        """Notify the risk manager of a trade outcome.

        After three consecutive failures the circuit breaker is triggered
        automatically.
        """
        if success:
            self.circuit_breaker.consecutive_failed_trades = 0
        else:
            self.circuit_breaker.consecutive_failed_trades += 1
            if self.circuit_breaker.consecutive_failed_trades >= 3:
                self.trigger_circuit_breaker("consecutive failed trades >= 3")
