from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from gmgn_monitor.optimization_runner import (
    OBJECTIVE_REGISTRY,
    run_optimization,
)
from gmgn_monitor.parameter_optimizer import OptimizationResult


def test_run_optimization_mock_weights() -> None:
    result = run_optimization(
        wallet_source="mock",
        optimization_mode="weights",
        objective="sharpe_positive",
        max_evaluations=5,
        wallet_count=10,
        backtest_limit=2,
    )
    assert isinstance(result, OptimizationResult)
    assert result.iteration_count <= 5


def test_run_optimization_mock_thresholds() -> None:
    result = run_optimization(
        wallet_source="mock",
        optimization_mode="thresholds",
        objective="sharpe_positive",
        max_evaluations=5,
        wallet_count=10,
        backtest_limit=2,
    )
    assert isinstance(result, OptimizationResult)
    assert result.iteration_count <= 5


def test_run_optimization_mock_joint() -> None:
    result = run_optimization(
        wallet_source="mock",
        optimization_mode="joint",
        objective="sharpe_positive",
        max_evaluations=5,
        wallet_count=10,
        backtest_limit=2,
    )
    assert isinstance(result, OptimizationResult)
    assert result.iteration_count <= 5


def test_run_optimization_invalid_objective() -> None:
    with pytest.raises(ValueError, match="unknown objective"):
        run_optimization(objective="nonexistent")


def test_run_optimization_invalid_mode() -> None:
    with pytest.raises(ValueError, match="unknown optimization_mode"):
        run_optimization(optimization_mode="bogus")


def test_run_optimization_output_file(tmp_path: Path) -> None:
    output_path = tmp_path / "opt_result.json"
    result = run_optimization(
        wallet_source="mock",
        optimization_mode="weights",
        objective="sharpe_positive",
        max_evaluations=3,
        wallet_count=10,
        backtest_limit=2,
        output_path=str(output_path),
    )
    assert output_path.exists()
    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["objective"] == "sharpe_positive"
    assert data["mode"] == "weights"
    assert "best_weights" in data
    assert "best_thresholds" in data
    assert "metrics" in data


def test_run_optimization_wallet_source_json(tmp_path: Path) -> None:
    wallets = [
        {
            "wallet_address": f"W{i}",
            "chain": "solana",
            "total_trades_7d": 50,
            "total_trades_30d": 200,
            "win_rate_30d": 60.0,
            "total_profit_usd": 10000.0,
            "avg_holding_duration_hours": 24.0,
            "stablecoin_balance_usd": 1000.0,
            "portfolio_balance_usd": 10000.0,
        }
        for i in range(5)
    ]
    json_path = tmp_path / "wallets.json"
    json_path.write_text(json.dumps(wallets), encoding="utf-8")

    result = run_optimization(
        wallet_source=str(json_path),
        optimization_mode="weights",
        objective="sharpe_positive",
        max_evaluations=3,
        backtest_limit=2,
    )
    assert isinstance(result, OptimizationResult)


def test_run_optimization_wallet_source_jsonl(tmp_path: Path) -> None:
    wallets = [
        {
            "wallet_address": f"W{i}",
            "chain": "solana",
            "total_trades_7d": 50,
            "total_trades_30d": 200,
            "win_rate_30d": 60.0,
            "total_profit_usd": 10000.0,
            "avg_holding_duration_hours": 24.0,
            "stablecoin_balance_usd": 1000.0,
            "portfolio_balance_usd": 10000.0,
        }
        for i in range(5)
    ]
    jsonl_path = tmp_path / "wallets.jsonl"
    jsonl_path.write_text(
        "\n".join(json.dumps(w) for w in wallets), encoding="utf-8"
    )

    result = run_optimization(
        wallet_source=str(jsonl_path),
        optimization_mode="weights",
        objective="sharpe_positive",
        max_evaluations=3,
        backtest_limit=2,
    )
    assert isinstance(result, OptimizationResult)


def test_run_optimization_wallet_source_not_found() -> None:
    with pytest.raises(ValueError, match="wallet_source not found"):
        run_optimization(wallet_source="/nonexistent/path.json")


def test_objective_registry_keys() -> None:
    assert "sharpe_positive" in OBJECTIVE_REGISTRY
    assert "risk_adjusted" in OBJECTIVE_REGISTRY
    assert "profit_consistency" in OBJECTIVE_REGISTRY
    assert "whitelist_quality" in OBJECTIVE_REGISTRY
    assert "composite" in OBJECTIVE_REGISTRY
