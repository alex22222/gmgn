from __future__ import annotations

from dataclasses import dataclass, fields
from math import isfinite
from pathlib import Path
from typing import Any

from .wallet_robot_detector import WalletFeatures, detect_robot
from .serialization import load_json


@dataclass(frozen=True)
class FilterThresholds:
    """Configuration thresholds for wallet hard/soft filtering rules.

    Hard rules result in immediate rejection; soft rules apply score penalties.
    All percentage fields are expressed as 0-100 numbers (e.g. 80.0 means 80%).
    """

    # Hard-filter thresholds
    max_trades_7d: int = 500
    min_trades_30d: int = 10
    min_data_trades: int = 10
    min_win_rate_percent: float = 30.0
    min_total_profit_usd: float = 0.0
    min_avg_holding_hours: float = 1.0
    max_single_token_concentration_percent: float = 80.0
    max_self_transfer_ratio_percent: float = 50.0
    max_inactive_days: int = 7
    robot_hard_reject_score: float = 60.0

    # Soft-filter thresholds (penalties)
    soft_high_freq_min: int = 100
    robot_soft_reject_score: float = 40.0
    soft_short_hold_hours: float = 6.0
    soft_high_volatility: float = 0.5
    soft_turbo_slippage_threshold: float = 80.0
    soft_new_wallet_days: int = 14
    soft_low_diversification: float = 0.3
    soft_high_mev_threshold: float = 50.0
    soft_large_gambler_threshold: float = 50.0
    soft_low_sl_discipline_threshold: float = 30.0

    # Decision thresholds
    pass_score: int = 80
    watch_score: int = 60


def filter_wallet(
    features: WalletFeatures, thresholds: FilterThresholds | None = None
) -> dict[str, Any]:
    """Apply hard and soft filtering rules to a wallet and return a decision.

    The pipeline follows the existing project pattern:
        1. _hard_reject_reasons (one-vote veto)
        2. _soft_penalties (deduct points)
        3. Threshold-based decision (pass / watch / reject)

    Args:
        features: WalletFeatures containing the wallet's data fields.
        thresholds: Optional FilterThresholds override. Defaults to standard values.

    Returns:
        A dict with keys:
            wallet_address, decision (pass/watch/reject), score (0-100),
            reasons (list[str]), hard_rejected (bool), robot_score (float).
    """
    thresholds = thresholds or FilterThresholds()
    robot_score = detect_robot(features)

    hard_reject = _hard_reject_reasons(features, thresholds, robot_score)
    if hard_reject:
        return {
            "wallet_address": str(features.get("wallet_address", "")),
            "decision": "reject",
            "score": 0,
            "reasons": hard_reject,
            "hard_rejected": True,
            "robot_score": robot_score,
        }

    score = 100
    reasons: list[str] = []
    penalty = _soft_penalties(features, thresholds, robot_score, reasons)
    score -= penalty

    if score >= thresholds.pass_score:
        decision = "pass"
    elif score >= thresholds.watch_score:
        decision = "watch"
    else:
        decision = "reject"
        reasons.append("score below watch threshold")

    return {
        "wallet_address": str(features.get("wallet_address", "")),
        "decision": decision,
        "score": max(0, score),
        "reasons": reasons,
        "hard_rejected": False,
        "robot_score": robot_score,
    }


def _hard_reject_reasons(
    features: WalletFeatures, thresholds: FilterThresholds, robot_score: float
) -> list[str]:
    """Evaluate hard-filter rules (one-vote veto). Returns a list of reasons if any rule triggers."""
    reasons: list[str] = []

    trades_7d = _to_float(features.get("trades_7d", 0))
    trades_30d = _to_float(features.get("trades_30d", 0))
    win_rate = _to_float(features.get("win_rate_percent", 0))
    total_profit = _to_float(features.get("total_profit_usd", 0))
    avg_holding = _to_float(features.get("avg_holding_hours", 0))
    total_trades = _to_float(features.get("total_trades", 0))
    single_token_pct = _to_float(features.get("single_token_concentration_percent", 0))
    self_transfer_pct = _to_float(features.get("self_transfer_ratio_percent", 0))
    inactive_days = _to_float(features.get("inactive_days", 0))
    is_mev_attacker = bool(features.get("is_mev_attacker", False))
    is_dev_associated = bool(features.get("is_dev_associated", False))

    # H-01: Ultra-high frequency (bot)
    if trades_7d > thresholds.max_trades_7d:
        reasons.append(
            f"7-day trades {trades_7d:.0f} exceeds {thresholds.max_trades_7d} (bot pattern)"
        )

    # H-02: Insufficient data
    if total_trades < thresholds.min_data_trades:
        reasons.append(
            f"total trades {total_trades:.0f} below minimum {thresholds.min_data_trades}"
        )

    # H-03: Zero win rate with enough sample
    if total_trades > 20 and win_rate < thresholds.min_win_rate_percent:
        reasons.append(
            f"win rate {win_rate:.1f}% below {thresholds.min_win_rate_percent}% with {total_trades:.0f} trades"
        )

    # H-04: Sustained losses
    if total_trades > 50 and total_profit < thresholds.min_total_profit_usd:
        reasons.append(
            f"total profit ${total_profit:.2f} negative with {total_trades:.0f} trades"
        )

    # H-05: Extreme rapid in/out with volume
    if total_trades > 100 and avg_holding < thresholds.min_avg_holding_hours:
        reasons.append(
            f"avg holding {avg_holding:.2f}h below {thresholds.min_avg_holding_hours}h with {total_trades:.0f} trades"
        )

    # H-06: Single-token gambler
    if single_token_pct > thresholds.max_single_token_concentration_percent:
        reasons.append(
            f"single token concentration {single_token_pct:.1f}% exceeds "
            f"{thresholds.max_single_token_concentration_percent}%"
        )

    # H-07: Fake volume (self-transfers)
    if self_transfer_pct > thresholds.max_self_transfer_ratio_percent:
        reasons.append(
            f"self-transfer ratio {self_transfer_pct:.1f}% exceeds {thresholds.max_self_transfer_ratio_percent}%"
        )

    # H-08: Known MEV attacker
    if is_mev_attacker:
        reasons.append("wallet is flagged as MEV attacker")

    # H-09: Developer-associated wallet
    if is_dev_associated:
        reasons.append("wallet is associated with token developer")

    # H-10: Robot detection hard reject
    if robot_score >= thresholds.robot_hard_reject_score:
        reasons.append(
            f"robot score {robot_score:.1f} >= {thresholds.robot_hard_reject_score} (hard reject)"
        )

    # H-11: Excessive inactivity
    if inactive_days > thresholds.max_inactive_days:
        reasons.append(
            f"inactive for {inactive_days:.0f} days, exceeds {thresholds.max_inactive_days} days"
        )

    return reasons


def _soft_penalties(
    features: WalletFeatures,
    thresholds: FilterThresholds,
    robot_score: float,
    reasons: list[str],
) -> int:
    """Evaluate soft-filter rules and return total penalty points (0-100)."""
    penalty = 0

    trades_7d = _to_float(features.get("trades_7d", 0))
    avg_holding = _to_float(features.get("avg_holding_hours", 0))
    volatility = _to_float(features.get("volatility_30d", 0))
    turbo_pct = _to_float(features.get("turbo_slippage_usage_percent", 0))
    wallet_age_days = _to_float(features.get("wallet_age_days", 0))
    div_index = _to_float(features.get("diversification_index", 0))
    mev_pct = _to_float(features.get("mev_usage_percent", 0))
    pump_fun_pct = _to_float(features.get("pump_fun_interaction_percent", 0))
    large_gambler_pct = _to_float(features.get("large_gambler_ratio_percent", 0))
    sl_discipline = _to_float(features.get("stop_loss_trigger_rate_percent", 0))

    # S-01: High frequency (soft)
    if thresholds.soft_high_freq_min <= trades_7d <= thresholds.max_trades_7d:
        penalty += 10
        reasons.append(f"high frequency {trades_7d:.0f} trades/7d (-10)")

    # S-02: Short holding time
    if avg_holding < thresholds.soft_short_hold_hours:
        penalty += 8
        reasons.append(f"short holding time {avg_holding:.2f}h (-8)")

    # S-03: High volatility
    if volatility > thresholds.soft_high_volatility:
        penalty += 5
        reasons.append(f"high volatility {volatility:.2f} (-5)")

    # S-04: Turbo slippage preference
    if turbo_pct > thresholds.soft_turbo_slippage_threshold:
        penalty += 5
        reasons.append(f"turbo slippage usage {turbo_pct:.1f}% (-5)")

    # S-05: New wallet
    if wallet_age_days < thresholds.soft_new_wallet_days:
        penalty += 10
        reasons.append(f"new wallet {wallet_age_days:.0f}d (-10)")

    # S-06: Low diversification
    if div_index < thresholds.soft_low_diversification:
        penalty += 8
        reasons.append(f"low diversification {div_index:.2f} (-8)")

    # S-07: Excessive MEV usage
    if mev_pct > thresholds.soft_high_mev_threshold:
        penalty += 5
        reasons.append(f"high MEV usage {mev_pct:.1f}% (-5)")

    # S-08: Pump.fun only
    if pump_fun_pct >= 100.0:
        penalty += 10
        reasons.append("100% Pump.fun interaction (-10)")

    # S-09: Large gambler
    if large_gambler_pct > thresholds.soft_large_gambler_threshold:
        penalty += 8
        reasons.append(f"large gambler ratio {large_gambler_pct:.1f}% (-8)")

    # S-10: Poor stop-loss discipline
    if sl_discipline < thresholds.soft_low_sl_discipline_threshold:
        penalty += 5
        reasons.append(f"low stop-loss discipline {sl_discipline:.1f}% (-5)")

    # Robot soft penalty (between soft and hard thresholds)
    if thresholds.robot_soft_reject_score <= robot_score < thresholds.robot_hard_reject_score:
        penalty += 10
        reasons.append(f"elevated robot score {robot_score:.1f} (-10)")

    return penalty


def _to_float(value: Any) -> float:
    """Safely convert a value to float, treating invalid values as 0.0."""
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)) and isfinite(value):
        return float(value)
    return 0.0


class FilterConfig:
    """Chain-aware filter configuration, mirroring the existing ThresholdConfig pattern.

    Supports a *default* set of thresholds plus per-chain overrides.
    """

    def __init__(
        self,
        default: FilterThresholds | None = None,
        chains: dict[str, FilterThresholds] | None = None,
    ):
        self.default = default or FilterThresholds()
        self.chains = {k.lower(): v for k, v in (chains or {}).items()}

    def for_chain(self, chain: str) -> FilterThresholds:
        return self.chains.get(chain.lower(), self.default)


def load_filter_config(path: Path) -> FilterConfig:
    """Load a filter configuration JSON file with strict validation.

    The file must contain an object with optional 'default' and 'chains' keys.
    Unknown fields are rejected to prevent silent misconfiguration.

    Args:
        path: Path to the JSON configuration file.

    Returns:
        A FilterConfig with default and per-chain thresholds.
    """
    raw = load_json(path, label="filter config")
    if not isinstance(raw, dict):
        raise ValueError("filter config must be an object")

    default_values = raw.get("default", {})
    if not isinstance(default_values, dict):
        raise ValueError("default filter thresholds must be an object")

    chain_values = raw.get("chains", {})
    if not isinstance(chain_values, dict):
        raise ValueError("chains filter thresholds must be an object")

    default = _filter_thresholds_from_dict(default_values, FilterThresholds(), "default")
    chains = {
        chain.lower(): _filter_thresholds_from_dict(values, default, chain.lower())
        for chain, values in chain_values.items()
    }
    return FilterConfig(default=default, chains=chains)


def _filter_thresholds_from_dict(
    values: dict[str, Any], base: FilterThresholds, label: str
) -> FilterThresholds:
    """Merge override values into a base FilterThresholds, validating fields."""
    if not isinstance(values, dict):
        raise ValueError(f"{label} filter thresholds must be an object")

    allowed = {field.name for field in fields(FilterThresholds)}
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ValueError(f"unknown filter threshold fields: {', '.join(unknown)}")

    merged = {field.name: getattr(base, field.name) for field in fields(FilterThresholds)}
    merged.update(values)
    _validate_filter_threshold_values(merged)
    return FilterThresholds(**merged)


def _validate_filter_threshold_values(values: dict[str, Any]) -> None:
    """Validate that all FilterThresholds values are numeric and within bounds."""
    percent_fields = {
        "min_win_rate_percent",
        "max_single_token_concentration_percent",
        "max_self_transfer_ratio_percent",
        "soft_turbo_slippage_threshold",
        "soft_high_mev_threshold",
        "soft_large_gambler_threshold",
        "soft_low_sl_discipline_threshold",
        "robot_hard_reject_score",
        "robot_soft_reject_score",
    }

    for name, value in values.items():
        if isinstance(value, bool):
            continue
        if not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be numeric")
        if not isfinite(value):
            raise ValueError(f"{name} must be finite")
        if value < 0:
            raise ValueError(f"{name} must be non-negative")
        if name in percent_fields and value > 100:
            raise ValueError(f"{name} must be at most 100")

    if values["pass_score"] < values["watch_score"]:
        raise ValueError("pass_score must be greater than or equal to watch_score")
    if values["robot_hard_reject_score"] < values["robot_soft_reject_score"]:
        raise ValueError(
            "robot_hard_reject_score must be greater than or equal to robot_soft_reject_score"
        )
