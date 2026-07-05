from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gmgn_monitor.objective_functions import (
    composite_objective,
    profit_consistency,
    risk_adjusted_return,
    sharpe_positive_ratio,
    whitelist_quality,
)


def _make_result(
    sharpe: float = 1.0,
    expectancy: float = 5.0,
    total_return: float = 10.0,
    max_drawdown: float = -10.0,
    win_rate: float = 60.0,
    profit_factor: float = 2.0,
) -> dict:
    return {
        "sharpe_ratio": sharpe,
        "expectancy_after_costs_percent": expectancy,
        "total_return_percent": total_return,
        "max_drawdown_percent": max_drawdown,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
    }


# ---------------------------------------------------------------------------
# sharpe_positive_ratio
# ---------------------------------------------------------------------------


def test_sharpe_positive_ratio_basic() -> None:
    results = [_make_result(sharpe=2.0, expectancy=5.0) for _ in range(4)]
    assert sharpe_positive_ratio(results) == 2.0 * 1.0


def test_sharpe_positive_ratio_empty() -> None:
    assert sharpe_positive_ratio([]) == 0.0


def test_sharpe_positive_ratio_mixed() -> None:
    results = [
        _make_result(sharpe=2.0, expectancy=5.0),
        _make_result(sharpe=0.5, expectancy=-2.0),
    ]
    # positive ratio = 0.5, avg sharpe = 1.25
    assert sharpe_positive_ratio(results) == 0.5 * 1.25


# ---------------------------------------------------------------------------
# risk_adjusted_return
# ---------------------------------------------------------------------------


def test_risk_adjusted_return_basic() -> None:
    results = [_make_result(total_return=20.0, max_drawdown=-10.0) for _ in range(4)]
    # avg_return = 20, avg_drawdown = -10, penalty = max(0, 10-20)*0.5 = 0
    assert risk_adjusted_return(results) == 20.0


def test_risk_adjusted_return_empty() -> None:
    assert risk_adjusted_return([]) == 0.0


def test_risk_adjusted_return_deep_drawdown() -> None:
    results = [_make_result(total_return=30.0, max_drawdown=-60.0) for _ in range(2)]
    # avg_return = 30, avg_drawdown = -60, penalty = (60-20)*0.5 = 20
    assert risk_adjusted_return(results) == 30.0 - 20.0


# ---------------------------------------------------------------------------
# profit_consistency
# ---------------------------------------------------------------------------


def test_profit_consistency_basic() -> None:
    results = [_make_result(total_return=10.0, profit_factor=2.0) for _ in range(4)]
    score = profit_consistency(results)
    assert score > 0.0


def test_profit_consistency_empty() -> None:
    assert profit_consistency([]) == 0.0


def test_profit_consistency_negative_return() -> None:
    results = [_make_result(total_return=-5.0, profit_factor=1.0) for _ in range(3)]
    assert profit_consistency(results) == 0.0


# ---------------------------------------------------------------------------
# whitelist_quality
# ---------------------------------------------------------------------------


def test_whitelist_quality_basic() -> None:
    results = [_make_result(win_rate=80.0, expectancy=5.0) for _ in range(5)]
    # positive_ratio = 1.0, avg_win_rate = 80.0 -> 1.0 * 0.8 = 0.8
    assert whitelist_quality(results) == 0.8


def test_whitelist_quality_empty() -> None:
    assert whitelist_quality([]) == 0.0


def test_whitelist_quality_mixed() -> None:
    results = [
        _make_result(win_rate=80.0, expectancy=5.0),
        _make_result(win_rate=60.0, expectancy=-2.0),
    ]
    # positive_ratio = 0.5, avg_win_rate = 70.0 -> 0.5 * 0.7 = 0.35
    assert whitelist_quality(results) == 0.35


# ---------------------------------------------------------------------------
# composite_objective
# ---------------------------------------------------------------------------


def test_composite_objective_default_weights() -> None:
    results = [_make_result() for _ in range(4)]
    score = composite_objective(results)
    assert score > 0.0


def test_composite_objective_custom_weights() -> None:
    results = [_make_result() for _ in range(4)]
    custom_weights = {"sharpe": 1.0, "return": 0.0, "positive_ratio": 0.0, "win_rate": 0.0, "drawdown": 0.0}
    score = composite_objective(results, weights=custom_weights)
    # Should be approximately avg_sharpe = 1.0
    assert score == pytest.approx(1.0, abs=0.01)


def test_composite_objective_empty() -> None:
    assert composite_objective([]) == 0.0
