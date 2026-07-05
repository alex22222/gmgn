from __future__ import annotations

import pytest

from gmgn_monitor.parameter_optimizer import (
    OptimizationResult,
    ParameterOptimizer,
    _frange,
    _generate_threshold_combinations,
    _generate_weight_combinations,
    _wallet_to_filter_features,
    _wallet_to_scoring_features,
)
from gmgn_monitor.wallet_filter import FilterThresholds
from gmgn_monitor.wallet_scorer import WalletScoringWeights


def _make_wallet(
    win_rate: float = 60.0,
    total_profit: float = 50000.0,
    trades_7d: float = 72.0,
    trades_30d: float = 280.0,
    avg_holding: float = 36.5,
) -> dict:
    return {
        "wallet_address": "MockWallet111111111111111111111111111111111111",
        "chain": "solana",
        "first_seen_at": "2025-01-15T08:30:00Z",
        "total_trades_7d": trades_7d,
        "total_trades_30d": trades_30d,
        "win_rate_30d": win_rate,
        "avg_investment_usd": 1500.0,
        "avg_profit_usd": 850.0,
        "total_profit_usd": total_profit,
        "avg_holding_duration_hours": avg_holding,
        "stablecoin_balance_usd": 2500.0,
        "portfolio_balance_usd": 15000.0,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_frange_inclusive() -> None:
    vals = _frange(0.1, 0.3, 0.05)
    assert vals == [0.1, 0.15, 0.2, 0.25, 0.3]


def test_generate_weight_combinations_basic() -> None:
    ranges = {"profit": (0.25, 0.25, 0.05), "risk": (0.25, 0.25, 0.05), "frequency": (0.25, 0.25, 0.05), "portfolio": (0.05, 0.05, 0.05), "behavior": (0.1, 0.1, 0.05), "consistency": (0.1, 0.1, 0.05)}
    combos = _generate_weight_combinations(ranges)
    assert len(combos) == 1
    assert combos[0]["profitability"] == 0.25
    assert combos[0]["risk_control"] == 0.25
    assert combos[0]["activity"] == 0.25
    assert combos[0]["stability"] == 0.05
    assert combos[0]["win_rate"] == 0.1
    assert combos[0]["consistency"] == 0.1


def test_generate_weight_combinations_sum_filter() -> None:
    ranges = {"profit": (0.15, 0.35, 0.05), "risk": (0.10, 0.25, 0.05)}
    # Only include combos that sum to ~1.0 - with 2 fields this won't happen
    combos = _generate_weight_combinations(ranges)
    # Should be empty because no combination of just 2 fields sums to 1.0
    # Actually with these 2 fields it could sum to 1.0: 0.75 + 0.25 = 1.0
    for c in combos:
        total = sum(c.values())
        assert pytest.approx(total, abs=0.01) == 1.0


def test_generate_weight_combinations_max_limit() -> None:
    ranges = {"profit": (0.15, 0.35, 0.05), "risk": (0.10, 0.25, 0.05), "frequency": (0.10, 0.25, 0.05), "portfolio": (0.05, 0.15, 0.05), "behavior": (0.10, 0.25, 0.05), "consistency": (0.05, 0.15, 0.05)}
    combos = _generate_weight_combinations(ranges, max_combinations=10)
    assert len(combos) <= 10


def test_generate_threshold_combinations_basic() -> None:
    ranges = {"pass_score": (50, 60, 5), "watch_score": (30, 40, 5)}
    combos = _generate_threshold_combinations(ranges)
    assert len(combos) == 9  # 3 * 3
    for c in combos:
        assert "pass_score" in c
        assert "watch_score" in c


# ---------------------------------------------------------------------------
# Feature conversion helpers
# ---------------------------------------------------------------------------


def test_wallet_to_scoring_features_keys() -> None:
    wallet = _make_wallet()
    features = _wallet_to_scoring_features(wallet)
    assert "wallet_address" in features
    assert "profit_metrics" in features
    assert "risk_metrics" in features
    assert "frequency_metrics" in features


def test_wallet_to_filter_features_keys() -> None:
    wallet = _make_wallet()
    wf = _wallet_to_filter_features(wallet, score=75.0)
    assert wf.get("wallet_address") == wallet["wallet_address"]
    assert wf.get("total_score") == 75.0


# ---------------------------------------------------------------------------
# ParameterOptimizer
# ---------------------------------------------------------------------------


def test_optimizer_init_default_objective() -> None:
    opt = ParameterOptimizer()
    assert opt.objective_fn is not None


def test_optimizer_custom_objective() -> None:
    custom = lambda results: 42.0
    opt = ParameterOptimizer(objective_fn=custom)
    assert opt.objective_fn([]) == 42.0


def test_optimize_weights_returns_result() -> None:
    wallets = [_make_wallet() for _ in range(20)]
    opt = ParameterOptimizer()
    result = opt.optimize_weights(wallets, max_evaluations=10, backtest_limit=3)
    assert isinstance(result, OptimizationResult)
    assert isinstance(result.best_weights, WalletScoringWeights)
    assert isinstance(result.best_thresholds, FilterThresholds)
    assert result.iteration_count <= 10


def test_optimize_thresholds_returns_result() -> None:
    wallets = [_make_wallet() for _ in range(20)]
    opt = ParameterOptimizer()
    result = opt.optimize_thresholds(wallets, max_evaluations=10, backtest_limit=3)
    assert isinstance(result, OptimizationResult)
    assert isinstance(result.best_weights, WalletScoringWeights)
    assert isinstance(result.best_thresholds, FilterThresholds)
    assert result.iteration_count <= 10


def test_optimize_joint_returns_result() -> None:
    wallets = [_make_wallet() for _ in range(20)]
    opt = ParameterOptimizer()
    result = opt.optimize_joint(wallets, max_evaluations=10, backtest_limit=3)
    assert isinstance(result, OptimizationResult)
    assert isinstance(result.best_weights, WalletScoringWeights)
    assert isinstance(result.best_thresholds, FilterThresholds)
    assert result.iteration_count <= 10


def test_evaluate_config_returns_metrics() -> None:
    wallets = [_make_wallet() for _ in range(10)]
    opt = ParameterOptimizer()
    weights = WalletScoringWeights()
    thresholds = FilterThresholds()
    metrics = opt.evaluate_config(weights, thresholds, wallets, backtest_limit=3)
    assert "objective_score" in metrics
    assert "whitelist_count" in metrics
    assert "avg_score" in metrics
    assert "positive_ratio" in metrics
    assert "avg_sharpe" in metrics
    assert "avg_return" in metrics
    assert "backtest_count" in metrics


def test_evaluate_config_empty_wallets() -> None:
    opt = ParameterOptimizer()
    metrics = opt.evaluate_config(
        WalletScoringWeights(), FilterThresholds(), [], backtest_limit=3
    )
    assert metrics["objective_score"] == 0.0
    assert metrics["whitelist_count"] == 0
    assert metrics["backtest_count"] == 0


def test_best_score_better_than_or_equal_default() -> None:
    wallets = [_make_wallet() for _ in range(20)]
    opt = ParameterOptimizer()
    default_metrics = opt.evaluate_config(
        WalletScoringWeights(), FilterThresholds(), wallets, backtest_limit=3
    )
    result = opt.optimize_weights(wallets, max_evaluations=10, backtest_limit=3)
    # The optimized score should be at least as good as the default config
    assert result.objective_score >= default_metrics["objective_score"] - 1e-9


def test_optimize_weights_with_small_range() -> None:
    wallets = [_make_wallet() for _ in range(10)]
    opt = ParameterOptimizer()
    ranges = {
        "profit": (0.25, 0.25, 0.05),
        "risk": (0.20, 0.20, 0.05),
        "frequency": (0.15, 0.15, 0.05),
        "portfolio": (0.10, 0.10, 0.05),
        "behavior": (0.15, 0.15, 0.05),
        "consistency": (0.15, 0.15, 0.05),
    }
    result = opt.optimize_weights(wallets, weight_ranges=ranges, max_evaluations=5, backtest_limit=2)
    assert result.iteration_count == 1
    assert result.best_weights.profitability == 0.25
