from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt
from typing import Any


@dataclass(frozen=True)
class WalletFeatures:
    """Immutable wrapper for wallet feature data used by robot detector and filter.

    Attributes:
        data: A dictionary of wallet features. Expected keys include:
            wallet_address, trades_7d, trades_30d, total_trades, win_rate_percent,
            total_profit_usd, avg_holding_hours, single_token_concentration_percent,
            self_transfer_ratio_percent, inactive_days, is_mev_attacker,
            is_dev_associated, trade_intervals_seconds, fees_sol_list,
            trade_hours_of_day, volatility_30d, turbo_slippage_usage_percent,
            wallet_age_days, diversification_index, mev_usage_percent,
            pump_fun_interaction_percent, large_gambler_ratio_percent,
            stop_loss_trigger_rate_percent.
    """

    data: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WalletFeatures:
        return cls(data)

    def get(self, field: str, default: Any = None) -> Any:
        return self.data.get(field, default)


def detect_robot(features: WalletFeatures) -> float:
    """Detect robot-like behavior in a wallet and return a 0-100 suspicion score.

    Higher scores indicate stronger robot signals. Scores >= 60 are typically
    used for hard rejection; 40-59 for soft penalty; < 40 for normal human.

    Dimensions (per spec):
        1. Trade frequency anomaly (30%)
        2. Trade interval consistency (25%) — coefficient of variation
        3. Holding time anomaly (20%) — very short holds indicate botting
        4. Gas/fee pattern rigidity (10%) — fixed gas is bot-like
        5. Time-of-day uniformity (15%) — 24h uniform distribution is bot-like

    Args:
        features: WalletFeatures instance with raw wallet data.

    Returns:
        Robot suspicion score in [0.0, 100.0].
    """
    score = 0.0

    score += _score_trade_frequency(features)
    score += _score_interval_consistency(features)
    score += _score_holding_time(features)
    score += _score_gas_pattern(features)
    score += _score_time_uniformity(features)

    return min(100.0, max(0.0, score))


def _score_trade_frequency(features: WalletFeatures) -> float:
    """Score based on 7-day trade count. Max 30 points.

    Missing data is treated as neutral (0 points).
    """
    trades_7d = features.get("trades_7d")
    if trades_7d is None:
        return 0.0
    avg_daily = _to_float(trades_7d) / 7.0

    if avg_daily > 100.0:
        return 30.0
    if avg_daily > 50.0:
        return 20.0
    if avg_daily > 30.0:
        return 10.0
    return 0.0


def _score_interval_consistency(features: WalletFeatures) -> float:
    """Score based on trade interval coefficient of variation. Max 25 points.

    Very regular intervals (CV < 0.2) strongly suggest automation.
    Missing data is treated as neutral (0 points).
    """
    intervals = features.get("trade_intervals_seconds")
    if intervals is None or not isinstance(intervals, list):
        return 0.0

    valid = [x for x in intervals if isinstance(x, (int, float)) and isfinite(x) and x > 0]
    if len(valid) < 20:
        return 0.0

    mean = sum(valid) / len(valid)
    if mean <= 0.0:
        return 0.0

    variance = sum((x - mean) ** 2 for x in valid) / len(valid)
    std = sqrt(variance)
    cv = std / mean

    if cv < 0.2:
        return 25.0
    if cv < 0.5:
        return 15.0
    return 0.0


def _score_holding_time(features: WalletFeatures) -> float:
    """Score based on average holding duration. Max 20 points.

    Bots typically hold positions for minutes rather than hours.
    Missing data is treated as neutral (0 points).
    """
    avg_hold = features.get("avg_holding_hours")
    if avg_hold is None:
        return 0.0
    avg_hold = _to_float(avg_hold)

    if avg_hold < 0.083:  # < 5 minutes
        return 20.0
    if avg_hold < 0.5:  # < 30 minutes
        return 10.0
    return 0.0


def _score_gas_pattern(features: WalletFeatures) -> float:
    """Score based on fee/gas variance. Max 10 points.

    Bots often use fixed or tightly clustered gas fees.
    Missing data is treated as neutral (0 points).
    """
    fees = features.get("fees_sol_list")
    if fees is None or not isinstance(fees, list):
        return 0.0

    valid = [x for x in fees if isinstance(x, (int, float)) and isfinite(x) and x >= 0]
    if len(valid) < 10:
        return 0.0

    mean = sum(valid) / len(valid)
    if mean <= 0.0:
        return 0.0

    variance = sum((x - mean) ** 2 for x in valid) / len(valid)
    std = sqrt(variance)
    cv = std / mean

    if cv < 0.1:
        return 10.0
    if cv < 0.2:
        return 5.0
    return 0.0


def _score_time_uniformity(features: WalletFeatures) -> float:
    """Score based on hour-of-day uniformity. Max 15 points.

    Humans tend to trade during waking hours; bots trade uniformly 24/7.
    Uses a chi-squared-like statistic against uniform distribution.
    Missing data is treated as neutral (0 points).
    """
    hours = features.get("trade_hours_of_day")
    if hours is None or not isinstance(hours, list):
        return 0.0

    valid = [x for x in hours if isinstance(x, (int, float)) and isfinite(x) and 0 <= x <= 23]
    if len(valid) < 20:
        return 0.0

    bins = [0] * 24
    for h in valid:
        bins[int(h)] += 1

    total = len(valid)
    expected = total / 24.0
    if expected <= 0.0:
        return 0.0

    # Chi-squared statistic; lower = more uniform = more bot-like
    chi2 = sum((obs - expected) ** 2 / expected for obs in bins)

    if chi2 < 20.0:
        return 15.0
    if chi2 < 50.0:
        return 8.0
    return 0.0


def _to_float(value: Any) -> float:
    """Safely convert a value to float, treating invalid values as 0.0."""
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)) and isfinite(value):
        return float(value)
    return 0.0
