from __future__ import annotations

import random
from dataclasses import dataclass, fields
from itertools import product
from math import isclose
from typing import Any, Callable

from .backtest_engine import BacktestEngine, StrategyConfig
from .backtest_strategies import FixedBuyStrategy
from .wallet_filter import FilterThresholds, WalletFeatures, filter_wallet
from .wallet_scorer import WalletScoringWeights, score_wallet


__all__ = [
    "OptimizationResult",
    "ParameterOptimizer",
]


# Map short weight-range keys to WalletScoringWeights field names.
_WEIGHT_NAME_MAP: dict[str, str] = {
    "profit": "profitability",
    "risk": "risk_control",
    "frequency": "activity",
    "portfolio": "stability",
    "behavior": "win_rate",
    "consistency": "consistency",
}


# Reverse map for returning readable names.
_WEIGHT_FIELD_TO_SHORT: dict[str, str] = {
    v: k for k, v in _WEIGHT_NAME_MAP.items()
}


@dataclass(frozen=True)
class OptimizationResult:
    """Immutable result of a parameter optimization run."""

    best_weights: WalletScoringWeights
    best_thresholds: FilterThresholds
    objective_score: float
    iteration_count: int
    metrics: dict[str, float]


# ---------------------------------------------------------------------------
# Default objective
# ---------------------------------------------------------------------------


def _default_objective(results: list[dict]) -> float:
    """Sharpe ratio * positive ratio."""
    if not results:
        return 0.0
    positive = sum(
        1 for r in results if r.get("expectancy_after_costs_percent", 0) > 0
    )
    positive_ratio = positive / len(results)
    avg_sharpe = sum(r.get("sharpe_ratio", 0) for r in results) / len(results)
    return avg_sharpe * positive_ratio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _frange(start: float, stop: float, step: float) -> list[float]:
    """Generate a list of floats from start to stop (inclusive)."""
    vals: list[float] = []
    v = start
    while v <= stop + 1e-9:
        vals.append(round(v, 4))
        v += step
    return vals


def _irange(start: int, stop: int, step: int) -> list[int]:
    """Generate a list of ints from start to stop (inclusive)."""
    return list(range(start, stop + 1, step))


def _generate_weight_combinations(
    weight_ranges: dict[str, tuple[float, float, float]],
    max_combinations: int | None = None,
) -> list[dict[str, float]]:
    """Generate all weight combinations that sum to approximately 1.0."""
    # Map short names to actual field names
    mapped_ranges: dict[str, list[float]] = {}
    for short_name, (start, stop, step) in weight_ranges.items():
        field_name = _WEIGHT_NAME_MAP.get(short_name, short_name)
        mapped_ranges[field_name] = _frange(start, stop, step)

    field_names = list(mapped_ranges.keys())
    value_lists = [mapped_ranges[f] for f in field_names]

    valid_combinations: list[dict[str, float]] = []
    for combo in product(*value_lists):
        combo_dict = dict(zip(field_names, combo))
        total = sum(combo_dict.values())
        if isclose(total, 1.0, abs_tol=0.01):
            valid_combinations.append(combo_dict)

    if max_combinations and len(valid_combinations) > max_combinations:
        # Deterministic sampling: take evenly spaced items
        step = len(valid_combinations) // max_combinations
        valid_combinations = valid_combinations[:: max(step, 1)]
        valid_combinations = valid_combinations[:max_combinations]

    return valid_combinations


def _generate_threshold_combinations(
    threshold_ranges: dict[str, tuple[int, int, int]],
) -> list[dict[str, int]]:
    """Generate all threshold combinations."""
    mapped_ranges: dict[str, list[int]] = {}
    for name, (start, stop, step) in threshold_ranges.items():
        mapped_ranges[name] = _irange(start, stop, step)

    names = list(mapped_ranges.keys())
    value_lists = [mapped_ranges[n] for n in names]

    return [dict(zip(names, combo)) for combo in product(*value_lists)]


# ---------------------------------------------------------------------------
# Wallet feature conversion helpers
# ---------------------------------------------------------------------------


def _wallet_to_scoring_features(wallet: dict[str, Any]) -> dict[str, Any]:
    """Convert a flat wallet dict to nested features for score_wallet."""
    total_profit = wallet.get("total_profit_usd", 0) or 0
    avg_profit = wallet.get("avg_profit_usd", 0) or 0
    avg_invest = wallet.get("avg_investment_usd", 0) or 0
    win_rate = wallet.get("win_rate_30d", 0) or 0
    trades_7d = wallet.get("total_trades_7d", 0) or 0
    trades_30d = wallet.get("total_trades_30d", 0) or 0
    avg_holding = wallet.get("avg_holding_duration_hours", 0) or 0
    stablecoin = wallet.get("stablecoin_balance_usd", 0) or 0
    portfolio = wallet.get("portfolio_balance_usd", 1) or 1
    sol_price = 150.0

    return {
        "wallet_address": wallet.get("wallet_address", ""),
        "chain": wallet.get("chain", "solana"),
        "profit_metrics": {
            "total_pnl_sol": total_profit / sol_price,
            "win_rate_percent": win_rate,
            "avg_profit_per_trade_sol": avg_profit / sol_price,
            "profit_factor": 2.5,
            "profit_loss_ratio": 2.0 if avg_profit > 0 else 1.0,
            "profit_sol_30d": total_profit / sol_price,
            "max_consecutive_losses": 2,
        },
        "risk_metrics": {
            "max_drawdown_percent": 25.0,
            "avg_loss_per_trade_sol": -1.5,
            "stop_loss_discipline_percent": 75.0,
            "sharpe_ratio": 1.5,
            "sortino_ratio": 2.0,
        },
        "frequency_metrics": {
            "trades_7d": trades_7d,
            "trades_30d": trades_30d,
            "avg_holding_hours": avg_holding,
            "median_holding_hours": avg_holding,
            "avg_daily_trades": trades_30d / 30.0 if trades_30d else 0,
            "days_since_last_trade": 1,
        },
        "portfolio_metrics": {
            "stablecoin_ratio_percent": min(100.0, stablecoin / max(portfolio, 1) * 100),
            "diversification_index": 0.6,
            "concentration_risk": "low",
            "avg_position_sol": avg_invest / sol_price if avg_invest else 0,
        },
        "behavior_flags": {
            "mev_attacker": False,
            "dev_wallet": False,
            "known_scammer": False,
            "bot_pattern": False,
        },
        "behavioral_metrics": {
            "bot_pattern_score": 10.0,
            "sniper_detected": False,
            "mev_usage_percent": 0.0,
        },
        "token_preference": {
            "pump_fun_interaction_percent": 20.0,
        },
        "first_seen_at": wallet.get("first_seen_at", ""),
        "total_transactions": trades_30d,
    }


def _wallet_to_filter_features(
    wallet: dict[str, Any], score: float
) -> WalletFeatures:
    """Convert a flat wallet dict to WalletFeatures for filter_wallet."""
    return WalletFeatures(
        data={
            "wallet_address": wallet.get("wallet_address", ""),
            "chain": wallet.get("chain", "solana"),
            "total_trades": wallet.get("total_trades_30d", 0) or 0,
            "trades_7d": wallet.get("total_trades_7d", 0) or 0,
            "trades_30d": wallet.get("total_trades_30d", 0) or 0,
            "win_rate_percent": wallet.get("win_rate_30d", 0) or 0,
            "total_profit_usd": wallet.get("total_profit_usd", 0) or 0,
            "avg_holding_hours": wallet.get("avg_holding_duration_hours", 0) or 0,
            "stablecoin_balance_usd": wallet.get("stablecoin_balance_usd", 2500.0),
            "portfolio_balance_usd": wallet.get("portfolio_balance_usd", 15000.0),
            "total_score": score,
            "single_token_concentration_percent": 20.0,
            "self_transfer_ratio_percent": 5.0,
            "is_mev_attacker": False,
            "is_dev_associated": False,
            "inactive_days": 1,
            "volatility_30d": 0.3,
            "turbo_slippage_usage_percent": 0.0,
            "wallet_age_days": 30,
            "diversification_index": 0.6,
            "mev_usage_percent": 0.0,
            "pump_fun_interaction_percent": 20.0,
            "large_gambler_ratio_percent": 10.0,
            "stop_loss_trigger_rate_percent": 75.0,
        }
    )


# ---------------------------------------------------------------------------
# Deterministic backtest helper
# ---------------------------------------------------------------------------


def _run_backtest_for_wallet(
    wallet_address: str, score: float, backtest_id: str = ""
) -> dict[str, Any]:
    """Run a deterministic backtest for a single wallet and return result dict."""
    # Use wallet address hash as seed for determinism
    seed = hash(wallet_address) % 10000
    rng = random.Random(seed)

    # Slightly bias price drift based on wallet score so optimization
    # has a meaningful signal to learn from.
    drift_bias = (score - 50) / 5000.0  # -0.01 to +0.01

    price_data: dict[str, list[dict[str, Any]]] = {}
    for i in range(3):
        token_addr = f"OptToken{i}_{wallet_address[:8]}"
        base_price = 100.0 + rng.uniform(-30, 50)
        series = []
        current_price = base_price
        for t in range(15):
            ts = f"2025-07-01T{t:02d}:00:00Z"
            change = rng.uniform(-0.15, 0.25) + drift_bias
            current_price = current_price * (1 + change)
            series.append({"timestamp": ts, "price": round(current_price, 4)})
        price_data[token_addr] = series

    strategy = FixedBuyStrategy(fixed_sol_amount=0.5)
    engine = BacktestEngine()
    result = engine.run_backtest(
        wallet_address, price_data, strategy.to_config(), backtest_id=backtest_id
    )
    return result.to_dict()


# ---------------------------------------------------------------------------
# Parameter Optimizer
# ---------------------------------------------------------------------------


class ParameterOptimizer:
    """Optimize wallet scoring weights and filter thresholds via grid search."""

    def __init__(
        self, objective_fn: Callable[[list[dict]], float] | None = None
    ) -> None:
        self.objective_fn = objective_fn or _default_objective
        self._eval_count = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def optimize_weights(
        self,
        wallets: list[dict[str, Any]],
        weight_ranges: dict[str, tuple[float, float, float]] | None = None,
        thresholds: FilterThresholds | None = None,
        max_evaluations: int = 100,
        backtest_limit: int = 10,
    ) -> OptimizationResult:
        """Grid-search over dimension weights with fixed thresholds."""
        weight_ranges = weight_ranges or {
            "profit": (0.15, 0.35, 0.05),
            "risk": (0.10, 0.25, 0.05),
            "frequency": (0.10, 0.25, 0.05),
            "portfolio": (0.05, 0.15, 0.05),
            "behavior": (0.10, 0.25, 0.05),
            "consistency": (0.05, 0.15, 0.05),
        }
        thresholds = thresholds or FilterThresholds()

        combinations = _generate_weight_combinations(
            weight_ranges, max_combinations=max_evaluations
        )

        best_score = float("-inf")
        best_weights = WalletScoringWeights()
        best_metrics: dict[str, float] = {}

        for combo in combinations:
            weights = WalletScoringWeights(**combo)
            metrics = self.evaluate_config(
                weights, thresholds, wallets, backtest_limit=backtest_limit
            )
            score = metrics.get("objective_score", 0.0)
            if score > best_score:
                best_score = score
                best_weights = weights
                best_metrics = metrics

        self._eval_count = len(combinations)

        return OptimizationResult(
            best_weights=best_weights,
            best_thresholds=thresholds,
            objective_score=best_score,
            iteration_count=self._eval_count,
            metrics=best_metrics,
        )

    def optimize_thresholds(
        self,
        wallets: list[dict[str, Any]],
        threshold_ranges: dict[str, tuple[int, int, int]] | None = None,
        weights: WalletScoringWeights | None = None,
        max_evaluations: int = 100,
        backtest_limit: int = 10,
    ) -> OptimizationResult:
        """Grid-search over filter thresholds with fixed weights."""
        threshold_ranges = threshold_ranges or {
            "pass_score": (50, 80, 5),
            "watch_score": (30, 60, 5),
        }
        weights = weights or WalletScoringWeights()

        combinations = _generate_threshold_combinations(threshold_ranges)

        # Limit combinations if too many
        if len(combinations) > max_evaluations:
            step = len(combinations) // max_evaluations
            combinations = combinations[:: max(step, 1)]
            combinations = combinations[:max_evaluations]

        best_score = float("-inf")
        best_thresholds = FilterThresholds()
        best_metrics: dict[str, float] = {}

        for combo in combinations:
            thresholds = FilterThresholds(**combo)
            metrics = self.evaluate_config(
                weights, thresholds, wallets, backtest_limit=backtest_limit
            )
            score = metrics.get("objective_score", 0.0)
            if score > best_score:
                best_score = score
                best_thresholds = thresholds
                best_metrics = metrics

        self._eval_count = len(combinations)

        return OptimizationResult(
            best_weights=weights,
            best_thresholds=best_thresholds,
            objective_score=best_score,
            iteration_count=self._eval_count,
            metrics=best_metrics,
        )

    def optimize_joint(
        self,
        wallets: list[dict[str, Any]],
        weight_ranges: dict[str, tuple[float, float, float]] | None = None,
        threshold_ranges: dict[str, tuple[int, int, int]] | None = None,
        max_evaluations: int = 100,
        backtest_limit: int = 10,
    ) -> OptimizationResult:
        """Grid-search over weights and thresholds jointly."""
        weight_ranges = weight_ranges or {
            "profit": (0.15, 0.35, 0.05),
            "risk": (0.10, 0.25, 0.05),
            "frequency": (0.10, 0.25, 0.05),
            "portfolio": (0.05, 0.15, 0.05),
            "behavior": (0.10, 0.25, 0.05),
            "consistency": (0.05, 0.15, 0.05),
        }
        threshold_ranges = threshold_ranges or {
            "pass_score": (50, 80, 5),
            "watch_score": (30, 60, 5),
        }

        weight_combos = _generate_weight_combinations(weight_ranges)
        threshold_combos = _generate_threshold_combinations(threshold_ranges)

        # Budget allocation: try to cover both dimensions
        total_possible = len(weight_combos) * len(threshold_combos)
        if total_possible <= max_evaluations:
            # Evaluate everything
            evaluations = [
                (w, t) for w in weight_combos for t in threshold_combos
            ]
        else:
            # Interleaved sampling to explore both dimensions
            evaluations = []
            count = 0
            for w in weight_combos:
                for t in threshold_combos:
                    evaluations.append((w, t))
                    count += 1
                    if count >= max_evaluations:
                        break
                if count >= max_evaluations:
                    break

        best_score = float("-inf")
        best_weights = WalletScoringWeights()
        best_thresholds = FilterThresholds()
        best_metrics: dict[str, float] = {}

        for w_combo, t_combo in evaluations:
            weights = WalletScoringWeights(**w_combo)
            thresholds = FilterThresholds(**t_combo)
            metrics = self.evaluate_config(
                weights, thresholds, wallets, backtest_limit=backtest_limit
            )
            score = metrics.get("objective_score", 0.0)
            if score > best_score:
                best_score = score
                best_weights = weights
                best_thresholds = thresholds
                best_metrics = metrics

        self._eval_count = len(evaluations)

        return OptimizationResult(
            best_weights=best_weights,
            best_thresholds=best_thresholds,
            objective_score=best_score,
            iteration_count=self._eval_count,
            metrics=best_metrics,
        )

    def evaluate_config(
        self,
        weights: WalletScoringWeights,
        thresholds: FilterThresholds,
        wallets: list[dict[str, Any]],
        backtest_limit: int = 10,
    ) -> dict[str, float]:
        """Evaluate a single (weights, thresholds) configuration.

        Returns metrics dict including:
            objective_score, whitelist_count, avg_score, positive_ratio,
            avg_sharpe, avg_return, backtest_count.
        """
        # Score wallets
        scored = []
        for wallet in wallets:
            features = _wallet_to_scoring_features(wallet)
            result = score_wallet(features, weights=weights)
            scored.append((wallet, result))

        # Filter wallets
        filtered = []
        for wallet, score_result in scored:
            score_val = score_result.get("total_score", 0)
            wf = _wallet_to_filter_features(wallet, score_val)
            filter_result = filter_wallet(wf, thresholds=thresholds)
            filtered.append((wallet, score_result, filter_result))

        whitelist = [
            (w, s, f)
            for w, s, f in filtered
            if f.get("decision") == "pass"
        ]

        # Fallback: if no pass, use score >= 50
        if not whitelist:
            whitelist = [
                (w, s, f)
                for w, s, f in filtered
                if f.get("score", 0) >= 50
            ]

        # Backtest top wallets
        backtest_results: list[dict] = []
        for wallet, score_result, _ in whitelist[:backtest_limit]:
            score_val = score_result.get("total_score", 0)
            addr = wallet.get("wallet_address", "")
            result_dict = _run_backtest_for_wallet(addr, score_val)
            backtest_results.append(result_dict)

        # Compute objective
        objective_score = self.objective_fn(backtest_results)

        # Compute summary metrics
        whitelist_count = len(whitelist)
        avg_score = (
            sum(s.get("total_score", 0) for _, s, _ in whitelist) / whitelist_count
            if whitelist_count else 0.0
        )
        positive_ratio = (
            sum(
                1
                for r in backtest_results
                if r.get("expectancy_after_costs_percent", 0) > 0
            )
            / len(backtest_results)
            if backtest_results else 0.0
        )
        avg_sharpe = (
            sum(r.get("sharpe_ratio", 0) for r in backtest_results)
            / len(backtest_results)
            if backtest_results else 0.0
        )
        avg_return = (
            sum(r.get("total_return_percent", 0) for r in backtest_results)
            / len(backtest_results)
            if backtest_results else 0.0
        )

        return {
            "objective_score": objective_score,
            "whitelist_count": whitelist_count,
            "avg_score": avg_score,
            "positive_ratio": positive_ratio,
            "avg_sharpe": avg_sharpe,
            "avg_return": avg_return,
            "backtest_count": len(backtest_results),
        }
