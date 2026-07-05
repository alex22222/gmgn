from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gmgn_monitor.config_manager import ConfigManager
from gmgn_monitor.loop_engine import LoopEngine
from gmgn_monitor.backtest_engine import BacktestEngine
from gmgn_monitor.backtest_strategies import FixedBuyStrategy
from gmgn_monitor.wallet_scorer import score_wallet, WalletScoringWeights
from gmgn_monitor.wallet_filter import filter_wallet, WalletFeatures, FilterThresholds


class TestRunGmgnRealIteration:
    def test_run_real_iteration_with_mock_fallback(self, tmp_path: Path) -> None:
        """Test run_real_iteration with realistic mock fallback (no API key)."""
        import scripts.run_gmgn_real_iteration as runner
        with patch.object(ConfigManager, "gmgn_api_key", None):
            with patch.object(ConfigManager, "validate_api_keys", return_value={"gmgn_api_key": False}):
                summary = runner.run_real_iteration(
                    wallet_count=5,
                    backtest_limit=3,
                    output_dir=tmp_path,
                )
                assert "report_path" in summary
                assert "whitelist_path" in summary
                assert "summary_path" in summary
                assert summary["total_wallets"] > 0
                assert summary["whitelist_count"] >= 0
                # Artifacts should exist
                assert Path(summary["report_path"]).exists()
                assert Path(summary["whitelist_path"]).exists()
                assert Path(summary["summary_path"]).exists()

    def test_run_real_iteration_with_mocked_fetch(self, tmp_path: Path) -> None:
        """Mock wallet fetch and verify pipeline runs."""
        import scripts.run_gmgn_real_iteration as runner
        mock_wallets = [
            {
                "wallet_address": f"Wallet{i}111111111111111111111111111111111111",
                "chain": "solana",
                "total_profit_usd": 5000.0 + i * 1000,
                "win_rate_30d": 60.0 + i * 2,
                "avg_profit_usd": 100.0,
                "total_trades_7d": 50,
                "total_trades_30d": 200,
                "avg_holding_duration_hours": 12.0,
                "stablecoin_balance_usd": 2000.0,
                "portfolio_balance_usd": 15000.0,
                "max_drawdown": 30.0,
                "self_transfer_ratio_percent": 5.0,
                "is_mev_attacker": False,
                "is_dev_associated": False,
            }
            for i in range(10)
        ]
        with patch.object(ConfigManager, "gmgn_api_key", None):
            with patch.object(ConfigManager, "validate_api_keys", return_value={"gmgn_api_key": False}):
                with patch.object(runner.RealWalletFetcher, "run_fetch", return_value=mock_wallets):
                    summary = runner.run_real_iteration(
                        wallet_count=10,
                        backtest_limit=5,
                        output_dir=tmp_path,
                    )
                    assert summary["total_wallets"] == 10
                    assert summary["backtest_count"] >= 0

    def test_report_generation_artifacts(self, tmp_path: Path) -> None:
        """Test that run_real_iteration generates all required artifacts."""
        import scripts.run_gmgn_real_iteration as runner
        with patch.object(ConfigManager, "gmgn_api_key", None):
            with patch.object(ConfigManager, "validate_api_keys", return_value={"gmgn_api_key": False}):
                summary = runner.run_real_iteration(
                    wallet_count=5,
                    backtest_limit=3,
                    output_dir=tmp_path,
                )
                report_path = Path(summary["report_path"])
                whitelist_path = Path(summary["whitelist_path"])
                summary_path = Path(summary["summary_path"])
                assert report_path.exists()
                assert whitelist_path.exists()
                assert summary_path.exists()
                # Check report content
                report_content = report_path.read_text()
                assert "GMGN" in report_content
                # Check whitelist JSON
                whitelist = json.loads(whitelist_path.read_text())
                assert isinstance(whitelist, list)
                # Check summary JSON
                summary_data = json.loads(summary_path.read_text())
                assert "total_wallets" in summary_data
                assert "whitelist_count" in summary_data

    def test_summary_json_output(self, tmp_path: Path) -> None:
        """Test that summary JSON contains expected keys."""
        import scripts.run_gmgn_real_iteration as runner
        with patch.object(ConfigManager, "gmgn_api_key", None):
            with patch.object(ConfigManager, "validate_api_keys", return_value={"gmgn_api_key": False}):
                summary = runner.run_real_iteration(
                    wallet_count=5,
                    backtest_limit=3,
                    output_dir=tmp_path,
                )
                summary_path = Path(summary["summary_path"])
                summary_data = json.loads(summary_path.read_text())
                assert "total_wallets" in summary_data
                assert "whitelist_count" in summary_data
                assert "backtest_count" in summary_data
                assert "positive_ratio" in summary_data
                assert "go_decision" in summary_data
                assert "timestamp" in summary_data
                assert "chain" in summary_data

    def test_error_handling_api_failure(self, tmp_path: Path) -> None:
        """Test that API failure is handled gracefully with partial results."""
        import scripts.run_gmgn_real_iteration as runner
        with patch.object(ConfigManager, "gmgn_api_key", "test-key"):
            with patch.object(ConfigManager, "validate_api_keys", return_value={"gmgn_api_key": True}):
                with patch.object(runner.RealWalletFetcher, "run_fetch", side_effect=Exception("API error")):
                    summary = runner.run_real_iteration(
                        wallet_count=10,
                        backtest_limit=5,
                        output_dir=tmp_path,
                    )
                    assert "error" in summary
                    assert summary["total_wallets"] == 0

    def test_main_command_line_args(self, tmp_path: Path) -> None:
        """Test that main parses command-line args correctly."""
        import scripts.run_gmgn_real_iteration as runner
        with patch.object(ConfigManager, "gmgn_api_key", None):
            with patch.object(ConfigManager, "validate_api_keys", return_value={"gmgn_api_key": False}):
                with patch.object(runner, "run_real_iteration") as mock_run:
                    mock_run.return_value = {
                        "report_path": str(tmp_path / "report.md"),
                        "whitelist_path": str(tmp_path / "whitelist.json"),
                        "summary_path": str(tmp_path / "summary.json"),
                        "total_wallets": 50,
                        "whitelist_count": 5,
                        "backtest_count": 3,
                        "positive_ratio": 0.5,
                        "avg_sharpe": 1.0,
                        "avg_return": 10.0,
                        "avg_drawdown": -5.0,
                        "loop_healthy": 5,
                        "go_decision": True,
                        "timestamp": "20250703_120000",
                        "chain": "base",
                        "wallet_count": 50,
                        "backtest_limit": 5,
                    }
                    with patch.object(sys, "argv", [
                        "run_gmgn_real_iteration.py",
                        "--wallet-count", "50",
                        "--backtest-limit", "5",
                        "--chain", "base",
                        "--output-dir", str(tmp_path),
                    ]):
                        rc = runner.main()
                    assert rc == 0
                    mock_run.assert_called_once()
                    call_kwargs = mock_run.call_args[1]
                    assert call_kwargs["wallet_count"] == 50
                    assert call_kwargs["backtest_limit"] == 5
                    assert call_kwargs["chain"] == "base"

    def test_pipeline_with_empty_wallets(self, tmp_path: Path) -> None:
        """Test _run_pipeline handles empty wallet list."""
        import scripts.run_gmgn_real_iteration as runner
        lines: list[str] = []
        log = runner._log_fn(lines)
        result = runner._run_pipeline(
            [], WalletScoringWeights(), FilterThresholds(), 10, 50, log
        )
        assert result["scored_wallets"] == []
        assert result["whitelist"] == []
        assert result["backtest_results"] == []
        assert result["positive"] == 0

    def test_build_flat_features(self) -> None:
        """Test _build_flat_features converts nested features correctly."""
        import scripts.run_gmgn_real_iteration as runner
        nested = {
            "wallet_address": "w1",
            "chain": "solana",
            "total_trades": 100,
            "trades_7d": 20,
            "trades_30d": 80,
            "win_rate_percent": 60.0,
            "total_profit_usd": 5000.0,
            "avg_holding_hours": 12.0,
            "stablecoin_balance_usd": 2000.0,
            "portfolio_balance_usd": 15000.0,
            "single_token_concentration_percent": 20.0,
            "self_transfer_ratio_percent": 5.0,
            "is_mev_attacker": False,
            "is_dev_associated": False,
            "inactive_days": 0,
            "total_score": 85.0,
            "portfolio_metrics": {"stablecoin_ratio_percent": 10.0},
        }
        flat = runner._build_flat_features(nested)
        assert flat["wallet_address"] == "w1"
        assert flat["chain"] == "solana"
        assert flat["total_score"] == 85.0
        assert flat["stablecoin_balance_usd"] == 1500.0  # 10.0 * 150.0

    def test_mock_price_data(self) -> None:
        """Test _mock_price_data generates valid price series."""
        import scripts.run_gmgn_real_iteration as runner
        price_data = runner._mock_price_data("test_wallet")
        assert len(price_data) == 5
        for token, series in price_data.items():
            assert len(series) == 20
            for point in series:
                assert "timestamp" in point
                assert "price" in point
                assert point["price"] > 0

    def test_run_real_iteration_with_api_key(self, tmp_path: Path) -> None:
        """Test run_real_iteration when API key is present."""
        import scripts.run_gmgn_real_iteration as runner
        mock_wallets = [
            {
                "wallet_address": "RealWallet111111111111111111111111111111",
                "chain": "solana",
                "total_profit_usd": 10000.0,
                "win_rate_30d": 75.0,
                "avg_profit_usd": 200.0,
                "total_trades_7d": 80,
                "total_trades_30d": 300,
                "avg_holding_duration_hours": 24.0,
                "stablecoin_balance_usd": 5000.0,
                "portfolio_balance_usd": 50000.0,
                "max_drawdown": 20.0,
                "self_transfer_ratio_percent": 2.0,
                "is_mev_attacker": False,
                "is_dev_associated": False,
            }
        ]
        with patch.object(ConfigManager, "gmgn_api_key", "real-api-key"):
            with patch.object(ConfigManager, "validate_api_keys", return_value={"gmgn_api_key": True}):
                with patch.object(runner.RealWalletFetcher, "run_fetch", return_value=mock_wallets):
                    summary = runner.run_real_iteration(
                        wallet_count=1,
                        backtest_limit=1,
                        output_dir=tmp_path,
                    )
                    assert summary["total_wallets"] == 1
                    assert "report_path" in summary
