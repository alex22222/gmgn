from __future__ import annotations

from typing import Any

__all__ = [
    "sharpe_positive_ratio",
    "risk_adjusted_return",
    "profit_consistency",
    "whitelist_quality",
    "composite_objective",
]


def sharpe_positive_ratio(results: list[dict]) -> float:
    """Objective: average Sharpe ratio multiplied by positive-expectancy ratio.

    Rewards configurations that produce both high risk-adjusted returns
    and a high proportion of winning backtests.
    """
    if not results:
        return 0.0
    positive = sum(
        1 for r in results if r.get("expectancy_after_costs_percent", 0) > 0
    )
    positive_ratio = positive / len(results)
    avg_sharpe = sum(r.get("sharpe_ratio", 0) for r in results) / len(results)
    return avg_sharpe * positive_ratio


def risk_adjusted_return(results: list[dict]) -> float:
    """Objective: average return penalised by maximum drawdown.

    Higher is better.  Drawdowns below -50 % are heavily penalised.
    """
    if not results:
        return 0.0
    avg_return = sum(r.get("total_return_percent", 0) for r in results) / len(
        results
    )
    avg_drawdown = sum(r.get("max_drawdown_percent", 0) for r in results) / len(
        results
    )
    # Penalise deep drawdowns (drawdown is negative, so smaller = worse)
    penalty = max(0.0, abs(avg_drawdown) - 20.0) * 0.5
    return avg_return - penalty


def profit_consistency(results: list[dict]) -> float:
    """Objective: reward high profit factor and low variance in returns.

    Uses the coefficient of variation of total_return_percent as a penalty.
    """
    if not results:
        return 0.0
    returns = [r.get("total_return_percent", 0) for r in results]
    mean_return = sum(returns) / len(returns)
    if mean_return <= 0:
        return 0.0

    variance = sum((x - mean_return) ** 2 for x in returns) / len(returns)
    std = variance ** 0.5
    cv = std / mean_return if mean_return != 0 else float("inf")

    avg_profit_factor = sum(r.get("profit_factor", 0) for r in results) / len(
        results
    )
    return mean_return * avg_profit_factor / (1 + cv)


def whitelist_quality(results: list[dict]) -> float:
    """Objective: reward large, high-quality whitelist with minimal rejects.

    Uses a simplified proxy: positive ratio weighted by average win rate.
    """
    if not results:
        return 0.0
    positive = sum(
        1 for r in results if r.get("expectancy_after_costs_percent", 0) > 0
    )
    positive_ratio = positive / len(results)
    avg_win_rate = sum(r.get("win_rate", 0) for r in results) / len(results)
    return positive_ratio * (avg_win_rate / 100.0)


def composite_objective(
    results: list[dict], weights: dict[str, float] | None = None
) -> float:
    """Weighted composite of multiple sub-objectives.

    Default weights:
        sharpe: 0.30, return: 0.25, positive_ratio: 0.25,
        win_rate: 0.15, drawdown: 0.05
    """
    if not results:
        return 0.0

    weights = weights or {
        "sharpe": 0.30,
        "return": 0.25,
        "positive_ratio": 0.25,
        "win_rate": 0.15,
        "drawdown": 0.05,
    }

    avg_sharpe = sum(r.get("sharpe_ratio", 0) for r in results) / len(results)
    avg_return = sum(r.get("total_return_percent", 0) for r in results) / len(
        results
    )
    positive = sum(
        1 for r in results if r.get("expectancy_after_costs_percent", 0) > 0
    )
    positive_ratio = positive / len(results)
    avg_win_rate = sum(r.get("win_rate", 0) for r in results) / len(results)
    avg_drawdown = sum(r.get("max_drawdown_percent", 0) for r in results) / len(
        results
    )

    # Normalise drawdown to a 0-1 score (less negative is better)
    drawdown_score = max(0.0, 1.0 - abs(avg_drawdown) / 100.0)

    score = (
        weights.get("sharpe", 0.0) * avg_sharpe
        + weights.get("return", 0.0) * (avg_return / 100.0)
        + weights.get("positive_ratio", 0.0) * positive_ratio
        + weights.get("win_rate", 0.0) * (avg_win_rate / 100.0)
        + weights.get("drawdown", 0.0) * drawdown_score
    )
    return score
