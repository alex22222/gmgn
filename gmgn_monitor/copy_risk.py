"""Single risk sheet for copy trading.

Pipeline plans still read ``config/risk_limits.json``. Copy execution reads
``config/copy_risk.json`` so absolute SOL caps, leader score, signal age, and
the copy order lines live in one place. The monitor CSS engine still defaults
to pass 70 / watch 50; only the copy runner passes the lines from this sheet.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .risk_manager import RiskLimits
from .serialization import load_json


DEFAULT_COPY_RISK_PATH = Path(__file__).resolve().parent.parent / "config" / "copy_risk.json"


@dataclass(frozen=True)
class CopyRiskProfile:
    """Absolute copy limits plus the gates that decide a signal can be ordered."""

    max_single_trade_sol: float = 0.01
    max_daily_loss_sol: float = 0.03
    max_daily_trades: int = 3
    max_positions: int = 3
    max_single_position_percent: float = 2.0
    daily_loss_limit_percent: float = 5.0
    default_slippage_percent: float = 2.0
    max_slippage_percent: float = 5.0
    stop_loss_percent: float = -40.0
    take_profit_steps: tuple[tuple[float, float], ...] = (
        (100.0, 50.0),
        (300.0, 50.0),
    )
    min_leader_score: float = 65.0
    review_score: float = 60.0
    css_pass_score: float = 60.0
    css_watch_score: float = 45.0
    min_signal_quality: int = 50
    report_lookback_days: int = 30
    max_signal_age_minutes: int = 30
    dedup_window_seconds: int = 300

    def to_risk_limits(self) -> RiskLimits:
        return RiskLimits(
            daily_loss_limit_percent=self.daily_loss_limit_percent,
            max_single_position_percent=self.max_single_position_percent,
            max_total_positions=self.max_positions,
            default_stop_loss_percent=self.stop_loss_percent,
            circuit_breaker_cooldown_seconds=600,
            kill_switch=False,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_single_trade_sol": self.max_single_trade_sol,
            "max_daily_loss_sol": self.max_daily_loss_sol,
            "max_daily_trades": self.max_daily_trades,
            "max_positions": self.max_positions,
            "max_single_position_percent": self.max_single_position_percent,
            "default_slippage_percent": self.default_slippage_percent,
            "max_slippage_percent": self.max_slippage_percent,
            "stop_loss_percent": self.stop_loss_percent,
            "min_leader_score": self.min_leader_score,
            "review_score": self.review_score,
            "css_pass_score": self.css_pass_score,
            "css_watch_score": self.css_watch_score,
            "min_signal_quality": self.min_signal_quality,
            "report_lookback_days": self.report_lookback_days,
            "max_signal_age_minutes": self.max_signal_age_minutes,
            "dedup_window_seconds": self.dedup_window_seconds,
        }

    def order_block_reason(self, amount_sol: float, daily_pnl_sol: float, slippage_percent: float) -> str | None:
        """Return why a sized order must not be placed, if any."""
        if amount_sol <= 0:
            return "amount must be positive"
        if amount_sol - self.max_single_trade_sol > 1e-9:
            return "exceeds max_single_trade_sol"
        if daily_pnl_sol <= -self.max_daily_loss_sol:
            return "daily loss limit"
        if slippage_percent - self.max_slippage_percent > 1e-9:
            return "exceeds max_slippage_percent"
        return None


def load_copy_risk(path: Path | None = None) -> CopyRiskProfile:
    """Load the copy risk sheet. A missing file falls back to the tiny-real defaults."""
    target = path or DEFAULT_COPY_RISK_PATH
    if not target.exists():
        return CopyRiskProfile()
    raw = load_json(target, label="copy risk")
    if not isinstance(raw, dict):
        raise ValueError("copy risk config must be an object")
    limits = raw.get("limits") if isinstance(raw.get("limits"), dict) else {}
    gates = raw.get("gates") if isinstance(raw.get("gates"), dict) else {}
    steps = limits.get("take_profit_steps")
    parsed_steps: tuple[tuple[float, float], ...] = CopyRiskProfile.take_profit_steps
    if isinstance(steps, list) and steps:
        parsed_steps = tuple(
            (float(step["price_change_percent"]), float(step["sell_percent"]))
            for step in steps
            if isinstance(step, dict)
        )
    profile = CopyRiskProfile(
        max_single_trade_sol=_float(limits, "max_single_trade_sol", 0.01),
        max_daily_loss_sol=_float(limits, "max_daily_loss_sol", 0.03),
        max_daily_trades=_int(limits, "max_daily_trades", 3),
        max_positions=_int(limits, "max_positions", 3),
        max_single_position_percent=_float(limits, "max_single_position_percent", 2.0),
        daily_loss_limit_percent=_float(limits, "daily_loss_limit_percent", 5.0),
        default_slippage_percent=_float(limits, "default_slippage_percent", 2.0),
        max_slippage_percent=_float(limits, "max_slippage_percent", 5.0),
        stop_loss_percent=_float(limits, "stop_loss_percent", -40.0),
        take_profit_steps=parsed_steps or CopyRiskProfile.take_profit_steps,
        min_leader_score=_float(gates, "min_leader_score", 65.0),
        review_score=_float(gates, "review_score", 60.0),
        css_pass_score=_float(gates, "css_pass_score", 60.0),
        css_watch_score=_float(gates, "css_watch_score", 45.0),
        min_signal_quality=_int(gates, "min_signal_quality", 50),
        report_lookback_days=_int(gates, "report_lookback_days", 30),
        max_signal_age_minutes=_int(gates, "max_signal_age_minutes", 30),
        dedup_window_seconds=_int(gates, "dedup_window_seconds", 300),
    )
    if profile.max_single_trade_sol <= 0 or profile.max_single_trade_sol > 0.01:
        raise ValueError("max_single_trade_sol must be within (0, 0.01]")
    if profile.max_daily_loss_sol <= 0 or profile.max_daily_loss_sol > 0.03:
        raise ValueError("max_daily_loss_sol must be within (0, 0.03]")
    if profile.max_slippage_percent <= 0 or profile.max_slippage_percent > 5:
        raise ValueError("max_slippage_percent must be within (0, 5]")
    if profile.stop_loss_percent >= 0:
        raise ValueError("stop_loss_percent must be negative")
    if profile.max_signal_age_minutes <= 0:
        raise ValueError("max_signal_age_minutes must be positive")
    if profile.min_leader_score < profile.review_score:
        raise ValueError("min_leader_score must be at least review_score")
    if not 0.0 <= profile.css_watch_score <= profile.css_pass_score <= 100.0:
        raise ValueError("css_pass_score must be between css_watch_score and 100")
    if profile.css_pass_score < 50.0:
        raise ValueError("css_pass_score must stay at least 50")
    return profile


def _float(source: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(source.get(key, default))
    except (TypeError, ValueError):
        return default


def _int(source: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(source.get(key, default))
    except (TypeError, ValueError):
        return default
