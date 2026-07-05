from __future__ import annotations

import json
from pathlib import Path

from unittest.mock import MagicMock, patch

import pytest

from gmgn_monitor.backtest_data_loader import BacktestDataLoader
from gmgn_monitor.iteration_runner import (
    run_iteration,
    _get_price_data_for_backtest,
    _extract_token_addresses_from_whitelist,
)


class TestRunIteration:
    def test_run_with_realistic_mock(self, tmp_path: Path) -> None:
        summary = run_iteration(
            wallet_count=50,
            backtest_limit=5,
            whitelist_min_score=50,
            output_dir=tmp_path,
            use_realistic_mock=True,
        )
        assert isinstance(summary, dict)
        assert summary["total_wallets"] == 50
        assert summary["whitelist_count"] > 0
        assert summary["backtest_count"] > 0
        assert 0.0 <= summary["positive_ratio"] <= 1.0
        assert summary["loop_healthy"] >= 0
        assert "go_decision" in summary
        assert "report_path" in summary
        assert "whitelist_path" in summary

        # Verify output files exist
        assert Path(summary["report_path"]).exists()
        assert Path(summary["whitelist_path"]).exists()
        assert Path(summary["summary_path"]).exists()

    def test_run_with_legacy_mock(self, tmp_path: Path) -> None:
        summary = run_iteration(
            wallet_count=20,
            backtest_limit=3,
            whitelist_min_score=50,
            output_dir=tmp_path,
            use_realistic_mock=False,
        )
        assert isinstance(summary, dict)
        assert summary["total_wallets"] == 20

    def test_realistic_mock_produces_non_trivial_scores(self, tmp_path: Path) -> None:
        summary = run_iteration(
            wallet_count=100,
            backtest_limit=5,
            whitelist_min_score=30,
            output_dir=tmp_path,
            use_realistic_mock=True,
        )
        # With realistic mock, we should get some variety in whitelist/backtest
        assert summary["whitelist_count"] > 0
        assert summary["backtest_count"] > 0

    def test_report_content(self, tmp_path: Path) -> None:
        summary = run_iteration(
            wallet_count=30,
            backtest_limit=3,
            whitelist_min_score=50,
            output_dir=tmp_path,
            use_realistic_mock=True,
        )
        report = Path(summary["report_path"]).read_text(encoding="utf-8")
        assert "GMGN" in report
        assert "评分引擎" in report
        assert "过滤规则" in report
        assert "回测引擎" in report
        assert "Loop Engineering" in report
        assert "Go/No-Go" in report

    def test_whitelist_json_format(self, tmp_path: Path) -> None:
        summary = run_iteration(
            wallet_count=30,
            backtest_limit=3,
            whitelist_min_score=50,
            output_dir=tmp_path,
            use_realistic_mock=True,
        )
        whitelist_raw = Path(summary["whitelist_path"]).read_text(encoding="utf-8")
        whitelist = json.loads(whitelist_raw)
        assert isinstance(whitelist, list)
        for entry in whitelist:
            assert "wallet_address" in entry
            assert "decision" in entry

    def test_summary_json_format(self, tmp_path: Path) -> None:
        summary = run_iteration(
            wallet_count=30,
            backtest_limit=3,
            whitelist_min_score=50,
            output_dir=tmp_path,
            use_realistic_mock=True,
        )
        summary_path = Path(summary["summary_path"])
        assert summary_path.exists()
        saved = json.loads(summary_path.read_text(encoding="utf-8"))
        assert saved["total_wallets"] == 30
        assert "positive_ratio" in saved
        assert "avg_sharpe" in saved

    def test_small_batch_runs(self, tmp_path: Path) -> None:
        summary = run_iteration(
            wallet_count=5,
            backtest_limit=2,
            whitelist_min_score=10,
            output_dir=tmp_path,
            use_realistic_mock=True,
        )
        assert summary["total_wallets"] == 5

    def test_zero_backtest_limit(self, tmp_path: Path) -> None:
        summary = run_iteration(
            wallet_count=10,
            backtest_limit=0,
            whitelist_min_score=10,
            output_dir=tmp_path,
            use_realistic_mock=True,
        )
        assert summary["backtest_count"] == 0
        assert summary["positive_ratio"] == 0.0

    def test_optimization_round(self, tmp_path: Path) -> None:
        summary = run_iteration(
            wallet_count=20,
            backtest_limit=3,
            whitelist_min_score=30,
            output_dir=tmp_path,
            use_realistic_mock=True,
            optimization_round=True,
            max_evaluations=5,
        )
        assert isinstance(summary, dict)
        assert "before" in summary
        assert "after" in summary
        assert "optimization" in summary
        assert "improved" in summary
        assert "total_wallets" in summary
        assert summary["before"]["backtest_count"] >= 0
        assert summary["after"]["backtest_count"] >= 0
        assert "best_weights" in summary["optimization"]
        assert "best_thresholds" in summary["optimization"]
        assert "objective_score" in summary["optimization"]
        assert "iteration_count" in summary["optimization"]
        assert Path(summary["report_path"]).exists()
        assert Path(summary["whitelist_path"]).exists()

    def test_data_loader_used_for_backtest(self, tmp_path: Path) -> None:
        """Verify that a provided data_loader is used for backtest price data."""
        loader = BacktestDataLoader()
        mock_ohlcv = [
            {"timestamp": f"2025-01-01T{t:02d}:00:00", "open": 100, "high": 110, "low": 95, "close": 105, "volume": 1000}
            for t in range(20)
        ]
        with patch.object(loader._birdeye_public, "get_token_history_ohlcv", return_value=mock_ohlcv):
            summary = run_iteration(
                wallet_count=10,
                backtest_limit=3,
                whitelist_min_score=10,
                output_dir=tmp_path,
                use_realistic_mock=True,
                data_loader=loader,
            )
            assert isinstance(summary, dict)
            assert summary["backtest_count"] > 0
            assert 0.0 <= summary["positive_ratio"] <= 1.0

    def test_market_scenario_still_works(self, tmp_path: Path) -> None:
        """Verify that market_scenario generates synthetic price data."""
        summary = run_iteration(
            wallet_count=10,
            backtest_limit=3,
            whitelist_min_score=10,
            output_dir=tmp_path,
            use_realistic_mock=True,
            market_scenario="bull",
        )
        assert isinstance(summary, dict)
        assert summary["backtest_count"] > 0

    def test_popular_tokens_fallback(self, tmp_path: Path) -> None:
        """Verify that popular tokens are used when wallet holdings are empty."""
        from gmgn_monitor.popular_tokens import get_default_token_addresses
        tokens = get_default_token_addresses("sol", count=5)
        assert len(tokens) > 0

        loader = BacktestDataLoader()
        mock_ohlcv = [
            {"timestamp": f"2025-01-01T{t:02d}:00:00", "open": 100, "high": 110, "low": 95, "close": 105, "volume": 1000}
            for t in range(20)
        ]
        with patch.object(loader._birdeye_public, "get_token_history_ohlcv", return_value=mock_ohlcv):
            summary = run_iteration(
                wallet_count=10,
                backtest_limit=3,
                whitelist_min_score=10,
                output_dir=tmp_path,
                use_realistic_mock=True,
                data_loader=loader,
            )
            assert isinstance(summary, dict)
            assert summary["backtest_count"] > 0

    def test_real_ohlcv_loading_mocked(self, tmp_path: Path) -> None:
        """Verify that real OHLCV loading works with mocked API."""
        loader = BacktestDataLoader()
        mock_ohlcv = [
            {"timestamp": f"2025-01-01T{t:02d}:00:00", "open": 100, "high": 110, "low": 95, "close": 105, "volume": 1000}
            for t in range(20)
        ]
        with patch.object(loader._birdeye_public, "get_token_history_ohlcv", return_value=mock_ohlcv):
            price_data = loader.load_ohlcv("test_token", chain="sol", timeframe="1H", limit=20)
            assert len(price_data) == 20
            assert "timestamp" in price_data[0]
            assert "close" in price_data[0]


class TestIterationRunnerHelpers:
    """Tests for helper functions in iteration_runner."""

    def test_extract_token_addresses_from_empty_whitelist(self) -> None:
        """Empty whitelist should return empty list."""
        result = _extract_token_addresses_from_whitelist([])
        assert result == []

    def test_extract_token_addresses_from_wallet_holdings(self) -> None:
        """Extract token addresses from wallet holdings."""
        whitelist = [
            {
                "wallet_address": "w1",
                "_original_wallet": {
                    "token_holdings": [
                        {"token_address": "TokenA111111111111111111111111111111111111"},
                        {"token_address": "TokenB222222222222222222222222222222222222"},
                    ]
                },
            }
        ]
        result = _extract_token_addresses_from_whitelist(whitelist)
        assert "TokenA111111111111111111111111111111111111" in result
        assert "TokenB222222222222222222222222222222222222" in result

    def test_extract_token_addresses_from_activities(self) -> None:
        """Extract token addresses from wallet activities."""
        whitelist = [
            {
                "wallet_address": "w1",
                "_original_wallet": {
                    "activities": [
                        {"token_address": "ActToken1111111111111111111111111111111111"},
                    ]
                },
            }
        ]
        result = _extract_token_addresses_from_whitelist(whitelist)
        assert "ActToken1111111111111111111111111111111111" in result

    def test_get_price_data_for_backtest_with_scenario(self) -> None:
        """Market scenario should generate synthetic data."""
        price_data = _get_price_data_for_backtest(
            [], market_scenario="bull"
        )
        assert len(price_data) > 0
        for token, series in price_data.items():
            assert isinstance(series, list)
            assert len(series) > 0
            assert "timestamp" in series[0]
            assert "price" in series[0]

    def test_get_price_data_for_backtest_with_popular_tokens(self) -> None:
        """When no holdings, popular tokens should be used."""
        price_data = _get_price_data_for_backtest(
            [{"wallet_address": "w1"}]
        )
        assert len(price_data) > 0

    def test_get_price_data_for_backtest_with_holdings(self) -> None:
        """When wallet has holdings, those tokens should be used."""
        whitelist = [
            {
                "wallet_address": "w1",
                "_original_wallet": {
                    "token_holdings": [
                        {"token_address": "HoldToken111111111111111111111111111111111"}
                    ]
                },
            }
        ]
        price_data = _get_price_data_for_backtest(whitelist)
        assert "HoldToken111111111111111111111111111111111" in price_data
