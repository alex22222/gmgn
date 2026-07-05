from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isclose, isfinite
from typing import Any


@dataclass(frozen=True)
class WalletScoringWeights:
    """Configurable weights and thresholds for the six-dimensional wallet scoring engine.

    Dimension weights must sum to approximately 1.0.  Decision thresholds determine
    the final copy/watch/observe/reject classification.
    """

    # Dimension weights (must sum to 1.0)
    profitability: float = 0.25
    win_rate: float = 0.20
    risk_control: float = 0.20
    consistency: float = 0.15
    activity: float = 0.10
    stability: float = 0.10

    # Decision thresholds
    copy_threshold: float = 80.0
    watch_threshold: float = 70.0
    observe_threshold: float = 40.0

    # Hard-reject thresholds
    min_trades_for_scoring: int = 10
    max_robot_score: float = 60.0
    max_trades_7d: int = 500
    min_win_rate_hard: float = 30.0
    min_avg_holding_hours: float = 1.0
    min_total_pnl: float = 0.0
    min_total_trades_for_pnl_check: int = 50

    # Quality-multiplier thresholds
    bot_pattern_penalty_threshold: float = 20.0
    win_rate_penalty_threshold: float = 50.0


@dataclass(frozen=True)
class WalletScoreResult:
    """Result of a wallet scoring run.  This is the in-memory counterpart to the
    scored-output dict returned by :func:`score_wallet`.
    """

    wallet_address: str
    chain: str
    total_score: float
    grade: str
    decision: str
    dimension_scores: dict[str, float]
    dimension_weights: dict[str, float]
    reasons: list[str]
    quality_multiplier: float
    risk_flags: dict[str, bool]


def score_wallet(
    features: dict[str, Any],
    weights: WalletScoringWeights | None = None,
) -> dict[str, Any]:
    """Score a single wallet using the six-dimensional weighted engine.

    The scoring flow follows the existing monitor pattern:

    1. **Hard reject** — one-veto disqualification (robot, insufficient data,
       ultra-high frequency, etc.).
    2. **Dimension scoring** — each of the six dimensions is scored 0–100 using
       tiered additive logic.
    3. **Weighted total** — dimensions are combined with configured weights.
    4. **Quality multiplier** — penalties for risk flags, bot patterns, or low
       win rate.
    5. **Threshold decision** — copy / watch / observe / reject based on total
       score.

    Args:
        features: Wallet feature dictionary.  Expected nested keys mirror the
            ``WalletFeatures`` schema (e.g. ``profit_metrics.win_rate_percent``).
            Missing or malformed nested values are treated as ``0``.
        weights: Optional scoring weights.  Defaults to :class:`WalletScoringWeights`.

    Returns:
        A dict compatible with the ``WalletScore`` JSON schema, containing
        ``wallet_address``, ``chain``, ``total_score``, ``grade``, ``decision``,
        ``dimension_scores``, ``dimension_weights``, ``reasons``,
        ``quality_multiplier``, and ``risk_flags``.
    """
    weights = weights or WalletScoringWeights()
    reasons: list[str] = []

    hard_reject = _hard_reject_reasons(features, weights)
    if hard_reject:
        return _build_reject_output(features, weights, hard_reject)

    # Compute per-dimension scores (0–100)
    dim_scores = {
        'profitability': _score_profitability(features),
        'win_rate': _score_win_rate(features),
        'risk_control': _score_risk_control(features),
        'consistency': _score_consistency(features),
        'activity': _score_activity(features),
        'stability': _score_stability(features),
    }

    total_weight = sum(getattr(weights, d) for d in dim_scores)
    if not isfinite(total_weight) or total_weight <= 0:
        raise ValueError('dimension weights must sum to a positive finite number')
    if not isclose(total_weight, 1.0, abs_tol=0.01):
        raise ValueError(f'dimension weights must sum to 1.0 (got {total_weight})')

    raw_score = sum(dim_scores[d] * getattr(weights, d) for d in dim_scores)
    quality_multiplier = _compute_quality_multiplier(features, weights)
    total_score = min(100.0, raw_score * quality_multiplier)

    grade = _compute_grade(total_score)
    decision = _compute_decision(total_score, weights)

    _append_dimension_reasons(dim_scores, reasons)
    if decision == 'reject':
        reasons.append('score below observe threshold')

    return {
        'wallet_address': features.get('wallet_address', ''),
        'chain': features.get('chain', 'solana'),
        'total_score': round(total_score, 2),
        'grade': grade,
        'decision': decision,
        'dimension_scores': {k: round(v, 2) for k, v in dim_scores.items()},
        'dimension_weights': {k: getattr(weights, k) for k in dim_scores},
        'reasons': reasons,
        'quality_multiplier': round(quality_multiplier, 2),
        'risk_flags': _collect_risk_flags(features),
    }


# ---------------------------------------------------------------------------
# Hard reject (one-veto) logic
# ---------------------------------------------------------------------------

def _hard_reject_reasons(
    features: dict[str, Any],
    weights: WalletScoringWeights,
) -> list[str]:
    """Return a list of hard-reject reasons; non-empty means immediate disqualification."""
    reasons: list[str] = []

    # H-10: Insufficient data
    total_trades = _get_nested(features, 'frequency_metrics', 'trades_7d') or 0
    if total_trades < weights.min_trades_for_scoring:
        reasons.append(f'insufficient trades: {total_trades} < {weights.min_trades_for_scoring}')

    # H-01: Ultra-high frequency bot
    trades_7d = _get_nested(features, 'frequency_metrics', 'trades_7d') or 0
    if trades_7d > weights.max_trades_7d:
        reasons.append(f'ultra-high frequency bot: {trades_7d} trades in 7d > {weights.max_trades_7d}')

    # H-02: Zero win rate with sufficient trades
    win_rate = _get_nested(features, 'profit_metrics', 'win_rate_percent') or 0
    total_trades_est = _get_nested(features, 'frequency_metrics', 'trades_30d') or 0
    if win_rate < weights.min_win_rate_hard and total_trades_est > 20:
        reasons.append(f'win rate too low: {win_rate}% < {weights.min_win_rate_hard}% with >20 trades')

    # H-04: Ultra-fast trading (sniper)
    avg_holding = _get_nested(features, 'frequency_metrics', 'avg_holding_hours') or 0
    total_trades_all = _get_nested(features, 'total_transactions') or 0
    if avg_holding < weights.min_avg_holding_hours and total_trades_all > 100:
        reasons.append(
            f'sniper detected: avg hold {avg_holding}h < {weights.min_avg_holding_hours}h with >100 trades'
        )

    # H-03: Consistent losses
    total_pnl = _get_nested(features, 'profit_metrics', 'total_pnl_sol') or 0
    trades_for_pnl = _get_nested(features, 'frequency_metrics', 'trades_30d') or 0
    if total_pnl < weights.min_total_pnl and trades_for_pnl > weights.min_total_trades_for_pnl_check:
        reasons.append(
            f'consistent losses: total_pnl {total_pnl} < {weights.min_total_pnl} '
            f'with >{weights.min_total_trades_for_pnl_check} trades'
        )

    # Robot detection ( overrides H-01 when bot score is very high )
    robot_score = _get_nested(features, 'behavioral_metrics', 'bot_pattern_score') or 0
    if robot_score > weights.max_robot_score:
        reasons.append(f'robot detected: bot_pattern_score {robot_score} > {weights.max_robot_score}')

    return reasons


def _build_reject_output(
    features: dict[str, Any],
    weights: WalletScoringWeights,
    hard_reject: list[str],
) -> dict[str, Any]:
    """Build a zero-score reject output for hard-rejected wallets."""
    zero_dims = {
        'profitability': 0.0,
        'win_rate': 0.0,
        'risk_control': 0.0,
        'consistency': 0.0,
        'activity': 0.0,
        'stability': 0.0,
    }
    return {
        'wallet_address': features.get('wallet_address', ''),
        'chain': features.get('chain', 'solana'),
        'total_score': 0.0,
        'grade': 'E',
        'decision': 'reject',
        'dimension_scores': zero_dims,
        'dimension_weights': {k: getattr(weights, k) for k in zero_dims},
        'reasons': hard_reject,
        'quality_multiplier': 0.0,
        'risk_flags': _collect_risk_flags(features),
    }


# ---------------------------------------------------------------------------
# Dimension scoring (0–100 each)
# ---------------------------------------------------------------------------

def _score_profitability(features: dict[str, Any]) -> float:
    """Score profitability (0–100) based on win rate, P/L ratio, and 30d ROI."""
    base = 0.0

    # Win rate component (40 points)
    win_rate = _get_nested(features, 'profit_metrics', 'win_rate_percent') or 0
    if win_rate >= 70:
        base += 40
    elif win_rate >= 60:
        base += 32
    elif win_rate >= 50:
        base += 20
    else:
        base += max(0.0, win_rate * 0.4)

    # Profit/loss ratio component (30 points)
    pl_ratio = _get_nested(features, 'profit_metrics', 'profit_loss_ratio') or 0
    if pl_ratio >= 3.0:
        base += 30
    elif pl_ratio >= 2.0:
        base += 24
    elif pl_ratio >= 1.5:
        base += 18
    else:
        base += max(0.0, pl_ratio * 10.0)

    # 30d ROI component (30 points)
    profit_30d = _get_nested(features, 'profit_metrics', 'profit_sol_30d') or 0
    avg_position = _get_nested(features, 'capital_metrics', 'avg_position_sol') or 0
    trades_30d = _get_nested(features, 'frequency_metrics', 'trades_30d') or 1
    if avg_position > 0 and trades_30d > 0:
        roi_30d = profit_30d / (avg_position * trades_30d)
    else:
        roi_30d = 0.0

    if roi_30d >= 0.5:
        base += 30
    elif roi_30d >= 0.3:
        base += 24
    elif roi_30d >= 0.1:
        base += 18
    else:
        base += max(0.0, roi_30d * 60.0)

    return min(100.0, base)


def _score_win_rate(features: dict[str, Any]) -> float:
    """Score win rate dimension (0–100) directly from win rate percentage."""
    win_rate = _get_nested(features, 'profit_metrics', 'win_rate_percent') or 0
    if win_rate >= 70:
        return 100.0
    elif win_rate >= 60:
        return 85.0
    elif win_rate >= 50:
        return 65.0
    elif win_rate >= 40:
        return 45.0
    elif win_rate >= 30:
        return 25.0
    return max(0.0, win_rate * 0.8)


def _score_risk_control(features: dict[str, Any]) -> float:
    """Score risk control (0–100) based on max drawdown, Sharpe, and Sortino ratios."""
    base = 0.0

    # Max drawdown component (40 points) — lower is better
    max_dd = _get_nested(features, 'risk_metrics', 'max_drawdown_percent') or 0
    if max_dd <= 30:
        base += 40
    elif max_dd <= 40:
        base += 32
    elif max_dd <= 50:
        base += 24
    elif max_dd <= 65:
        base += 16
    else:
        base += max(0.0, 40.0 - (max_dd - 30.0) * 0.8)

    # Sharpe ratio component (30 points)
    sharpe = _get_nested(features, 'risk_metrics', 'sharpe_ratio') or 0
    if sharpe >= 2.0:
        base += 30
    elif sharpe >= 1.5:
        base += 24
    elif sharpe >= 1.0:
        base += 18
    else:
        base += max(0.0, sharpe * 18.0)

    # Sortino ratio component (30 points)
    sortino = _get_nested(features, 'risk_metrics', 'sortino_ratio') or 0
    if sortino >= 2.5:
        base += 30
    elif sortino >= 2.0:
        base += 24
    elif sortino >= 1.5:
        base += 18
    else:
        base += max(0.0, sortino * 20.0)

    return min(100.0, base)


def _score_consistency(features: dict[str, Any]) -> float:
    """Score consistency / discipline (0–100) based on holding stability,
    trade frequency stability, and consecutive loss control.
    """
    base = 0.0

    # Holding period stability (35 points)
    avg_holding = _get_nested(features, 'frequency_metrics', 'avg_holding_hours') or 0
    median_holding = _get_nested(features, 'frequency_metrics', 'median_holding_hours') or 0
    if avg_holding > 0:
        holding_cv = abs(avg_holding - median_holding) / avg_holding
    else:
        holding_cv = 1.0

    if avg_holding >= 24 and holding_cv <= 0.5:
        base += 35
    elif avg_holding >= 24:
        base += 28
    elif avg_holding >= 12:
        base += 21
    else:
        base += max(0.0, avg_holding * 1.5)

    # Trade frequency stability (35 points)
    trades_7d = _get_nested(features, 'frequency_metrics', 'trades_7d') or 0
    if 50 <= trades_7d <= 100:
        base += 35
    elif 30 <= trades_7d < 50:
        base += 28
    elif 100 < trades_7d <= 150:
        base += 21
    else:
        base += 14

    # Consecutive loss control (30 points)
    max_consecutive_losses = _get_nested(features, 'profit_metrics', 'max_consecutive_losses') or 0
    if max_consecutive_losses <= 3:
        base += 30
    elif max_consecutive_losses <= 5:
        base += 24
    elif max_consecutive_losses <= 8:
        base += 18
    else:
        base += max(0.0, 30.0 - (max_consecutive_losses - 3.0) * 3.0)

    return min(100.0, base)


def _score_activity(features: dict[str, Any]) -> float:
    """Score activity (0–100) based on trade frequency metrics."""
    base = 0.0

    # 7-day trade count (50 points)
    trades_7d = _get_nested(features, 'frequency_metrics', 'trades_7d') or 0
    if 50 <= trades_7d <= 100:
        base += 50
    elif 30 <= trades_7d < 50:
        base += 40
    elif 10 <= trades_7d < 30:
        base += 30
    elif trades_7d > 100:
        base += 20
    else:
        base += max(0.0, trades_7d * 2.0)

    # Average daily trades (30 points)
    avg_daily = _get_nested(features, 'frequency_metrics', 'avg_daily_trades') or 0
    if 5 <= avg_daily <= 15:
        base += 30
    elif 3 <= avg_daily < 5:
        base += 24
    elif 15 < avg_daily <= 25:
        base += 20
    else:
        base += max(0.0, avg_daily * 2.0)

    # 30-day trade count (20 points)
    trades_30d = _get_nested(features, 'frequency_metrics', 'trades_30d') or 0
    if 200 <= trades_30d <= 400:
        base += 20
    elif 100 <= trades_30d < 200:
        base += 16
    elif 50 <= trades_30d < 100:
        base += 12
    else:
        base += max(0.0, trades_30d * 0.05)

    return min(100.0, base)


def _score_stability(features: dict[str, Any]) -> float:
    """Score stability (0–100) based on account age, profit consistency, and bot pattern score."""
    base = 0.0

    # Account age (40 points)
    first_seen = _get_nested(features, 'first_seen_at') or ''
    days_alive = _parse_days_alive(first_seen)
    if days_alive >= 90:
        base += 40
    elif days_alive >= 60:
        base += 32
    elif days_alive >= 30:
        base += 24
    else:
        base += max(0.0, days_alive * 1.2)

    # Profit consistency (30 points)
    profit_7d = _get_nested(features, 'profit_metrics', 'total_pnl_sol') or 0
    profit_30d = _get_nested(features, 'profit_metrics', 'profit_sol_30d') or 0
    if profit_30d > 0 and profit_7d > 0:
        consistency = profit_7d / (profit_30d / 4.3)
        if 0.8 <= consistency <= 1.2:
            base += 30
        elif 0.5 <= consistency < 0.8:
            base += 24
        else:
            base += 18
    else:
        base += 10.0

    # Bot pattern score (30 points) — lower is better
    bot_score = _get_nested(features, 'behavioral_metrics', 'bot_pattern_score') or 0
    if bot_score <= 10:
        base += 30
    elif bot_score <= 20:
        base += 24
    elif bot_score <= 30:
        base += 18
    else:
        base += max(0.0, 30.0 - (bot_score - 30.0) * 0.5)

    return min(100.0, base)


# ---------------------------------------------------------------------------
# Quality multiplier and decision logic
# ---------------------------------------------------------------------------

def _compute_quality_multiplier(
    features: dict[str, Any],
    weights: WalletScoringWeights,
) -> float:
    """Apply quality penalties based on risk flags, bot patterns, and win rate."""
    multiplier = 1.0

    risk_flags = _collect_risk_flags(features)
    if any(risk_flags.values()):
        multiplier *= 0.5

    bot_score = _get_nested(features, 'behavioral_metrics', 'bot_pattern_score') or 0
    if bot_score > weights.bot_pattern_penalty_threshold:
        multiplier *= 0.7

    win_rate = _get_nested(features, 'profit_metrics', 'win_rate_percent') or 0
    if win_rate < weights.win_rate_penalty_threshold:
        multiplier *= 0.8

    return multiplier


def _collect_risk_flags(features: dict[str, Any]) -> dict[str, bool]:
    """Collect boolean risk flags from wallet features."""
    sniper = _get_nested(features, 'behavioral_metrics', 'sniper_detected') or False
    pump_fun = (_get_nested(features, 'token_preference', 'pump_fun_interaction_percent') or 0) > 80
    mev = (_get_nested(features, 'behavioral_metrics', 'mev_usage_percent') or 0) > 50
    return {
        'high_frequency_bot': sniper,
        'pump_fun_gambler': pump_fun,
        'mev_attacker': mev,
        'insider_related': False,
    }


def _compute_grade(score: float) -> str:
    """Map a 0–100 score to a letter grade."""
    if score >= 80:
        return 'A'
    elif score >= 70:
        return 'B'
    elif score >= 60:
        return 'C'
    elif score >= 40:
        return 'D'
    return 'E'


def _compute_decision(score: float, weights: WalletScoringWeights) -> str:
    """Map a score to a decision using configured thresholds."""
    if score >= weights.copy_threshold:
        return 'copy'
    elif score >= weights.watch_threshold:
        return 'watch'
    elif score >= weights.observe_threshold:
        return 'observe'
    return 'reject'


def _append_dimension_reasons(dim_scores: dict[str, float], reasons: list[str]) -> None:
    """Append qualitative reasons based on per-dimension scores."""
    for name, score in dim_scores.items():
        if score >= 80:
            reasons.append(f'{name} score {score:.0f} is excellent')
        elif score >= 60:
            reasons.append(f'{name} score {score:.0f} is good')
        elif score >= 40:
            reasons.append(f'{name} score {score:.0f} is moderate')
        else:
            reasons.append(f'{name} score {score:.0f} is weak')


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _add_score(condition: bool, points: int, reasons: list[str], reason: str) -> int:
    """Additive scoring helper compatible with the existing monitor pattern.

    If *condition* is true, append *reason* to *reasons* and return *points*.
    Otherwise return ``0``.
    """
    if condition:
        reasons.append(reason)
        return points
    return 0


def _get_nested(data: dict[str, Any], *keys: str) -> Any:
    """Safely traverse a nested dict, returning ``None`` on any missing key or type mismatch."""
    value = data
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _parse_days_alive(first_seen: str) -> int:
    """Parse an ISO timestamp and return the number of days since then."""
    if not first_seen:
        return 0
    try:
        normalized = first_seen[:-1] + '+00:00' if first_seen.endswith('Z') else first_seen
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return max(0, (now - dt).days)
    except ValueError:
        return 0
