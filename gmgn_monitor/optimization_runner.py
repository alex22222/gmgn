from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .objective_functions import (
    sharpe_positive_ratio,
    risk_adjusted_return,
    profit_consistency,
    whitelist_quality,
    composite_objective,
)
from .parameter_optimizer import OptimizationResult, ParameterOptimizer
from .wallet_fetcher import WalletFetcher
from .wallet_filter import FilterThresholds
from .wallet_scorer import WalletScoringWeights

__all__ = [
    "OBJECTIVE_REGISTRY",
    "run_optimization",
]


OBJECTIVE_REGISTRY: dict[str, Any] = {
    "sharpe_positive": sharpe_positive_ratio,
    "risk_adjusted": risk_adjusted_return,
    "profit_consistency": profit_consistency,
    "whitelist_quality": whitelist_quality,
    "composite": composite_objective,
}


def run_optimization(
    wallet_source: str = "mock",
    optimization_mode: str = "joint",
    objective: str = "sharpe_positive",
    max_evaluations: int = 100,
    output_path: str | None = None,
    backtest_limit: int = 10,
    wallet_count: int = 200,
) -> OptimizationResult:
    """High-level runner for parameter optimization.

    Args:
        wallet_source: ``"mock"`` for synthetic data, or a path to a JSON/JSONL
            file containing wallet dicts.
        optimization_mode: ``"weights"``, ``"thresholds"``, or ``"joint"``.
        objective: Name of the objective function to use (see
            :data:`OBJECTIVE_REGISTRY`).
        max_evaluations: Maximum number of configurations to evaluate.
        output_path: Optional path to write a JSON summary of the result.
        backtest_limit: Number of whitelist wallets to backtest per config.
        wallet_count: Number of mock wallets to generate when *wallet_source*
            is ``"mock"``.

    Returns:
        An :class:`OptimizationResult` with the best found configuration.
    """
    objective_fn = OBJECTIVE_REGISTRY.get(objective)
    if objective_fn is None:
        raise ValueError(
            f"unknown objective: {objective}. "
            f"Available: {', '.join(OBJECTIVE_REGISTRY)}"
        )

    # Load wallets
    if wallet_source == "mock":
        fetcher = WalletFetcher(mock=True)
        wallets = fetcher.run_fetch(batch_size=wallet_count, output_path=None)
    else:
        path = Path(wallet_source)
        if not path.exists():
            raise ValueError(f"wallet_source not found: {wallet_source}")
        if path.suffix == ".jsonl":
            wallets = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        else:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                wallets = raw
            elif isinstance(raw, dict):
                wallets = [raw]
            else:
                raise ValueError("wallet_source JSON must be a list or object")

    if not isinstance(wallets, list) or not wallets:
        raise ValueError("no wallets loaded")

    optimizer = ParameterOptimizer(objective_fn=objective_fn)

    if optimization_mode == "weights":
        result = optimizer.optimize_weights(
            wallets, max_evaluations=max_evaluations, backtest_limit=backtest_limit
        )
    elif optimization_mode == "thresholds":
        result = optimizer.optimize_thresholds(
            wallets, max_evaluations=max_evaluations, backtest_limit=backtest_limit
        )
    elif optimization_mode == "joint":
        result = optimizer.optimize_joint(
            wallets, max_evaluations=max_evaluations, backtest_limit=backtest_limit
        )
    else:
        raise ValueError(
            f"unknown optimization_mode: {optimization_mode}. "
            "Use 'weights', 'thresholds', or 'joint'."
        )

    if output_path is not None:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        summary = {
            "objective": objective,
            "mode": optimization_mode,
            "max_evaluations": max_evaluations,
            "best_objective_score": result.objective_score,
            "iteration_count": result.iteration_count,
            "best_weights": {
                f: getattr(result.best_weights, f)
                for f in result.best_weights.__dataclass_fields__
            },
            "best_thresholds": {
                f: getattr(result.best_thresholds, f)
                for f in result.best_thresholds.__dataclass_fields__
            },
            "metrics": result.metrics,
        }
        out.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    return result
