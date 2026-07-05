from __future__ import annotations

import json
import time
import urllib.error
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from gmgn_monitor.backtest_engine import BacktestEngine, StrategyConfig
from gmgn_monitor.backtest_strategies import FixedBuyStrategy
from gmgn_monitor.gmgn_api_client import GmgnApiClient, GmgnApiError
from gmgn_monitor.gmgn_data_mapper import (
    map_smartmoney_list_to_wallet_addresses,
    map_token_top_traders_to_wallet_addresses,
    map_wallet_stats_to_features,
)
from gmgn_monitor.real_wallet_fetcher import RealWalletFetcher
from gmgn_monitor.wallet_filter import FilterThresholds, filter_wallet
from gmgn_monitor.wallet_robot_detector import WalletFeatures
from gmgn_monitor.wallet_scorer import WalletScoringWeights, score_wallet


# ─────────────────────────── Fixtures ───────────────────────────

@pytest.fixture
def mock_gmgn_wallet_stats() -> dict[str, object]:
    """Return a realistic GMGN wallet_stats response for one wallet."""
    return {
        "wallet_address": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZR6Y7Q5XqK",
        "chain": "solana",
        "total_profit": 52000.0,
        "realized_profit": 30000.0,
        "unrealized_profit": 22000.0,
        "win_rate": 68.5,
        "total_trades": 342,
        "trades_7d": 72,
        "trades_30d": 280,
        "avg_holding_time": 36.5,
        "pnl_7d": 0.15,
        "pnl_30d": 0.25,
        "max_drawdown": 42.0,
        "portfolio_value": 15000.0,
        "balance_usd": 2500.0,
        "first_seen_at": "2025-01-15T08:30:00Z",
        "diversification_index": 0.68,
        "concentration_risk": 0.45,
        "mev_attacker": False,
        "dev_wallet": False,
        "known_scammer": False,
        "bot_pattern": False,
        "sniper_detected": False,
        "bot_pattern_score": 12.0,
        "mev_usage_percent": 15.0,
        "pump_fun_interaction_percent": 65.0,
        "avg_position_sol": 2.5,
        "sharpe_ratio": 1.85,
        "sortino_ratio": 2.45,
    }


@pytest.fixture
def mock_price_data() -> dict[str, list[dict[str, object]]]:
    """Return mock price data for backtesting."""
    return {
        "TOKEN1": [
            {"timestamp": "2026-01-01T12:00:00", "price": 1.0},
            {"timestamp": "2026-01-02T12:00:00", "price": 2.0},
        ],
        "TOKEN2": [
            {"timestamp": "2026-01-01T12:00:00", "price": 1.0},
            {"timestamp": "2026-01-02T12:00:00", "price": 1.5},
        ],
    }


@pytest.fixture
def mock_gmgn_api_response() -> dict[str, object]:
    """Return a full GMGN API response (with code/data/message)."""
    return {
        "code": 0,
        "data": {
            "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZR6Y7Q5XqK": {
                "wallet_address": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZR6Y7Q5XqK",
                "chain": "solana",
                "total_profit": 52000.0,
                "win_rate": 68.5,
                "total_trades": 342,
                "trades_7d": 72,
                "trades_30d": 280,
                "avg_holding_time": 36.5,
                "max_drawdown": 42.0,
                "portfolio_value": 15000.0,
                "balance_usd": 2500.0,
                "first_seen_at": "2025-01-15T08:30:00Z",
                "diversification_index": 0.68,
                "mev_attacker": False,
                "dev_wallet": False,
                "sniper_detected": False,
                "bot_pattern_score": 12.0,
                "mev_usage_percent": 15.0,
                "pump_fun_interaction_percent": 65.0,
                "avg_position_sol": 2.5,
                "sharpe_ratio": 1.85,
                "sortino_ratio": 2.45,
                "single_token_concentration_percent": 30.0,
                "self_transfer_ratio_percent": 5.0,
                "inactive_days": 3,
                "wallet_age_days": 90,
                "volatility_30d": 0.3,
                "turbo_slippage_usage_percent": 30.0,
                "large_gambler_ratio_percent": 30.0,
                "stop_loss_trigger_rate_percent": 50.0,
                "trade_intervals_seconds": [3600.0 + i * 300 for i in range(50)],
                "trade_hours_of_day": [8, 9, 10, 11, 12, 13, 14, 15, 16] * 10,
                "fees_sol_list": [0.005 + i * 0.001 for i in range(50)],
            }
        },
        "message": "",
    }


# ─────────────────────────── Integration Tests ───────────────────────────

class TestFullPipeline:
    def test_full_pipeline_with_mock_gmgn_data(
        self,
        mock_gmgn_api_response: dict[str, object],
    ) -> None:
        """Simulate GMGN API response, map to features, score, filter, assert outputs."""
        # Extract data from API response
        wallet_data = mock_gmgn_api_response["data"]
        assert isinstance(wallet_data, dict)
        raw_stats = wallet_data["7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZR6Y7Q5XqK"]
        assert isinstance(raw_stats, dict)

        # Step 1: Map to nested features
        features = map_wallet_stats_to_features(raw_stats)
        assert "wallet_address" in features
        assert features["wallet_address"] == "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZR6Y7Q5XqK"
        assert "profit_metrics" in features
        assert "risk_metrics" in features
        assert "frequency_metrics" in features

        # Step 2: Score
        score_result = score_wallet(features)
        assert score_result["decision"] in ("copy", "watch", "observe", "reject")
        assert score_result["total_score"] >= 0.0
        assert score_result["total_score"] <= 100.0
        assert "dimension_scores" in score_result
        assert "reasons" in score_result

        # Step 3: Filter (WalletFeatures needs flat fields with names filter expects)
        # GMGN uses "win_rate" but filter expects "win_rate_percent", etc.
        filter_input = {**raw_stats, "win_rate_percent": raw_stats["win_rate"], "avg_holding_hours": raw_stats["avg_holding_time"], "total_profit_usd": raw_stats["total_profit"]}
        wallet_features = WalletFeatures.from_dict(filter_input)
        filter_result = filter_wallet(wallet_features)
        assert filter_result["decision"] in ("pass", "watch", "reject")
        assert filter_result["score"] >= 0
        assert isinstance(filter_result["hard_rejected"], bool)
        assert "robot_score" in filter_result

    def test_data_mapper_produces_valid_score_features(
        self,
        mock_gmgn_wallet_stats: dict[str, object],
    ) -> None:
        """Verify mapped features contain all keys required by score_wallet."""
        features = map_wallet_stats_to_features(mock_gmgn_wallet_stats)

        # Required nested keys for score_wallet
        assert "wallet_address" in features
        assert "chain" in features
        assert "total_transactions" in features
        assert "first_seen_at" in features

        assert "profit_metrics" in features
        pm = features["profit_metrics"]
        for key in (
            "total_pnl_sol",
            "win_rate_percent",
            "avg_profit_per_trade_sol",
            "profit_factor",
            "profit_loss_ratio",
            "max_consecutive_losses",
            "profit_sol_30d",
            "profit_usd_30d",
        ):
            assert key in pm, f"Missing profit_metrics key: {key}"

        assert "risk_metrics" in features
        rm = features["risk_metrics"]
        for key in ("max_drawdown_percent", "sharpe_ratio", "sortino_ratio"):
            assert key in rm, f"Missing risk_metrics key: {key}"

        assert "frequency_metrics" in features
        fm = features["frequency_metrics"]
        for key in ("trades_7d", "trades_30d", "avg_holding_hours", "avg_daily_trades"):
            assert key in fm, f"Missing frequency_metrics key: {key}"

        assert "behavioral_metrics" in features
        bm = features["behavioral_metrics"]
        for key in ("bot_pattern_score", "sniper_detected", "mev_usage_percent"):
            assert key in bm, f"Missing behavioral_metrics key: {key}"

        assert "token_preference" in features
        tp = features["token_preference"]
        assert "pump_fun_interaction_percent" in tp

        assert "capital_metrics" in features
        cm = features["capital_metrics"]
        assert "avg_position_sol" in cm

    def test_end_to_end_with_mapped_data(
        self,
        mock_gmgn_wallet_stats: dict[str, object],
        mock_price_data: dict[str, list[dict[str, object]]],
    ) -> None:
        """Full pipeline: map -> score -> filter -> backtest."""
        # Map
        features = map_wallet_stats_to_features(mock_gmgn_wallet_stats)

        # Score
        score_result = score_wallet(features)
        assert score_result["total_score"] >= 0.0
        assert score_result["total_score"] <= 100.0

        # Filter (using the same raw stats with field names corrected for filter_wallet)
        filter_input = {**mock_gmgn_wallet_stats, "win_rate_percent": mock_gmgn_wallet_stats["win_rate"], "avg_holding_hours": mock_gmgn_wallet_stats["avg_holding_time"], "total_profit_usd": mock_gmgn_wallet_stats["total_profit"]}
        wallet_features = WalletFeatures.from_dict(filter_input)
        filter_result = filter_wallet(wallet_features)
        assert filter_result["decision"] in ("pass", "watch", "reject")

        # Backtest
        engine = BacktestEngine()
        strategy = FixedBuyStrategy().to_config()
        backtest_result = engine.run_backtest(
            wallet_address=features["wallet_address"],
            price_data=mock_price_data,
            strategy_config=strategy,
            backtest_id="integration-001",
        )
        assert backtest_result.total_trades >= 0
        assert isinstance(backtest_result.total_return_percent, float)
        assert backtest_result.backtest_id == "integration-001"
        assert backtest_result.wallet_address == features["wallet_address"]

    def test_real_fetcher_fallback_when_no_api_key(self) -> None:
        """Verify RealWalletFetcher falls back to mock when no API key is provided."""
        fetcher = RealWalletFetcher(api_key=None, chain="sol", mock_fallback=True)
        assert fetcher._is_mock()

        # Fetch should return mock data without crashing
        wallets = fetcher.fetch_smartmoney_wallets(limit=3)
        assert len(wallets) == 3
        for w in wallets:
            assert isinstance(w, dict)
            assert "wallet_address" in w

        stats = fetcher.fetch_wallet_stats(["addr1"])
        assert isinstance(stats, dict)
        assert "addr1" in stats

        features_list = fetcher.build_scored_features(stats)
        assert len(features_list) == 1
        assert "wallet_address" in features_list[0]
        assert "profit_metrics" in features_list[0]

    def test_api_client_rate_limit_retry(self) -> None:
        """Verify rate limit retry logic using mocked urllib."""
        client = GmgnApiClient(api_key="test-key")
        success_body = {"code": 0, "data": [{"wallet_address": "addr1"}], "message": ""}
        success_resp = MagicMock()
        success_resp.read.return_value = json.dumps(success_body).encode("utf-8")
        success_resp.__enter__ = MagicMock(return_value=success_resp)
        success_resp.__exit__ = MagicMock(return_value=False)

        rate_limit_err = urllib.error.HTTPError(
            url="https://openapi.gmgn.ai/v1/user/smartmoney",
            code=429,
            msg="Too Many Requests",
            hdrs={"x-ratelimit-reset": str(int(time.time()) + 1)},
            fp=BytesIO(b"{}"),
        )

        with patch("urllib.request.urlopen", side_effect=[rate_limit_err, success_resp]) as mock_urlopen:
            with patch("time.sleep") as mock_sleep:
                result = client.get_smartmoney()
                assert result == [{"wallet_address": "addr1"}]
                assert mock_urlopen.call_count == 2
                assert mock_sleep.call_count == 1

    def test_smartmoney_address_extraction(self) -> None:
        """Integration check: smartmoney response -> address list."""
        response = {
            "code": 0,
            "data": [
                {"wallet_address": "addr1"},
                {"wallet_address": "addr2"},
                {"wallet_address": "addr3"},
            ],
            "message": "",
        }
        addresses = map_smartmoney_list_to_wallet_addresses(response)
        assert addresses == ["addr1", "addr2", "addr3"]

    def test_top_traders_address_extraction(self) -> None:
        """Integration check: top traders response -> address list."""
        response = {
            "code": 0,
            "data": [
                {"wallet_address": "trader1"},
                {"wallet_address": "trader2"},
            ],
            "message": "",
        }
        addresses = map_token_top_traders_to_wallet_addresses(response)
        assert addresses == ["trader1", "trader2"]

    def test_pipeline_with_weak_wallet_rejected(self) -> None:
        """Simulate a weak wallet that gets rejected by scoring and filtering."""
        weak_stats = {
            "wallet_address": "WeakWallet111111111111111111111111111111",
            "chain": "solana",
            "total_profit": -1000.0,
            "total_profit_usd": -1000.0,
            "win_rate": 25.0,
            "win_rate_percent": 25.0,
            "total_trades": 60,
            "trades_7d": 550,  # ultra-high frequency -> hard reject
            "trades_30d": 60,
            "avg_holding_time": 0.3,  # sniper
            "max_drawdown": 80.0,
            "portfolio_value": 100.0,
            "balance_usd": 0.0,
            "first_seen_at": "2025-01-15T08:30:00Z",
            "diversification_index": 0.1,
            "mev_attacker": False,
            "dev_wallet": False,
            "sniper_detected": False,
            "bot_pattern_score": 65.0,  # robot detected
            "mev_usage_percent": 10.0,
            "pump_fun_interaction_percent": 50.0,
            "avg_position_sol": 1.0,
            "sharpe_ratio": -0.5,
            "sortino_ratio": -0.3,
            "single_token_concentration_percent": 85.0,
            "self_transfer_ratio_percent": 5.0,
            "inactive_days": 3,
            "wallet_age_days": 90,
            "volatility_30d": 0.8,
            "turbo_slippage_usage_percent": 30.0,
            "large_gambler_ratio_percent": 30.0,
            "stop_loss_trigger_rate_percent": 20.0,
            "trade_intervals_seconds": [60.0] * 50,
            "trade_hours_of_day": list(range(24)) * 5,
            "fees_sol_list": [0.005] * 50,
        }

        features = map_wallet_stats_to_features(weak_stats)
        score_result = score_wallet(features)
        assert score_result["decision"] == "reject"
        assert score_result["total_score"] == 0.0

        # Use field names that filter_wallet expects
        filter_input = {**weak_stats, "win_rate_percent": weak_stats["win_rate"], "avg_holding_hours": weak_stats["avg_holding_time"], "total_profit_usd": weak_stats["total_profit"]}
        wallet_features = WalletFeatures.from_dict(filter_input)
        filter_result = filter_wallet(wallet_features)
        assert filter_result["decision"] == "reject"
        assert filter_result["hard_rejected"] is True

    def test_pipeline_with_moderate_wallet_watch(self) -> None:
        """Simulate a moderate wallet that gets 'watch' or 'observe' decisions."""
        moderate_stats = {
            "wallet_address": "ModWallet2222222222222222222222222222222",
            "chain": "solana",
            "total_profit": 5000.0,
            "total_profit_usd": 5000.0,
            "win_rate": 55.0,
            "win_rate_percent": 55.0,
            "total_trades": 100,
            "trades_7d": 45,
            "trades_30d": 200,
            "avg_holding_time": 12.0,
            "max_drawdown": 50.0,
            "portfolio_value": 5000.0,
            "balance_usd": 500.0,
            "first_seen_at": "2025-01-15T08:30:00Z",
            "diversification_index": 0.45,
            "mev_attacker": False,
            "dev_wallet": False,
            "sniper_detected": False,
            "bot_pattern_score": 20.0,
            "mev_usage_percent": 10.0,
            "pump_fun_interaction_percent": 60.0,
            "avg_position_sol": 2.0,
            "sharpe_ratio": 1.2,
            "sortino_ratio": 1.5,
            "single_token_concentration_percent": 40.0,
            "self_transfer_ratio_percent": 5.0,
            "inactive_days": 3,
            "wallet_age_days": 60,
            "volatility_30d": 0.4,
            "turbo_slippage_usage_percent": 30.0,
            "large_gambler_ratio_percent": 30.0,
            "stop_loss_trigger_rate_percent": 50.0,
            "trade_intervals_seconds": [3600.0 + i * 300 for i in range(50)],
            "trade_hours_of_day": [8, 9, 10, 11, 12, 13, 14, 15, 16] * 10,
            "fees_sol_list": [0.005 + i * 0.001 for i in range(50)],
        }

        features = map_wallet_stats_to_features(moderate_stats)
        score_result = score_wallet(features)
        assert score_result["decision"] in ("watch", "observe", "copy")
        assert score_result["total_score"] > 0.0

        filter_input = {**moderate_stats, "win_rate_percent": moderate_stats["win_rate"], "avg_holding_hours": moderate_stats["avg_holding_time"], "total_profit_usd": moderate_stats["total_profit"]}
        wallet_features = WalletFeatures.from_dict(filter_input)
        filter_result = filter_wallet(wallet_features)
        assert filter_result["decision"] in ("pass", "watch", "reject")
        assert isinstance(filter_result["score"], int)

    def test_backtest_with_positive_expectancy(
        self,
        mock_gmgn_wallet_stats: dict[str, object],
    ) -> None:
        """Verify that a mapped + scored wallet can be backtested with positive expectancy."""
        # Winning price data
        price_data = {
            "WINNER": [
                {"timestamp": "2026-01-01T12:00:00", "price": 1.0},
                {"timestamp": "2026-01-02T12:00:00", "price": 5.0},
            ]
        }

        engine = BacktestEngine()
        strategy = FixedBuyStrategy().to_config()
        result = engine.run_backtest(
            wallet_address=mock_gmgn_wallet_stats["wallet_address"],  # type: ignore[index]
            price_data=price_data,
            strategy_config=strategy,
        )
        assert result.is_positive_expectancy() is True
        assert result.expectancy_after_costs_percent > 0

    def test_backtest_with_negative_expectancy(
        self,
        mock_gmgn_wallet_stats: dict[str, object],
    ) -> None:
        """Verify backtest handles losing price data correctly."""
        price_data = {
            "LOSER": [
                {"timestamp": "2026-01-01T12:00:00", "price": 1.0},
                {"timestamp": "2026-01-02T12:00:00", "price": 0.2},
            ]
        }

        engine = BacktestEngine()
        strategy = FixedBuyStrategy().to_config()
        result = engine.run_backtest(
            wallet_address=mock_gmgn_wallet_stats["wallet_address"],  # type: ignore[index]
            price_data=price_data,
            strategy_config=strategy,
        )
        assert result.is_positive_expectancy() is False
        assert result.expectancy_after_costs_percent < 0

    def test_api_client_error_propagation(self) -> None:
        """Verify that GmgnApiError is raised on API failures."""
        client = GmgnApiClient(api_key="bad-key")
        error_resp = MagicMock()
        error_resp.read.return_value = json.dumps(
            {"code": 40001, "data": None, "message": "Invalid API key"}
        ).encode("utf-8")
        error_resp.__enter__ = MagicMock(return_value=error_resp)
        error_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=error_resp):
            with pytest.raises(GmgnApiError) as exc_info:
                client.get_smartmoney()
            assert exc_info.value.code == 40001
            assert "Invalid API key" in str(exc_info.value)

    def test_mapper_with_partial_data(self) -> None:
        """Ensure mapper handles partially populated API data without crashing."""
        partial = {"wallet_address": "partial123", "win_rate": 50.0}
        features = map_wallet_stats_to_features(partial)
        assert features["wallet_address"] == "partial123"
        assert features["profit_metrics"]["win_rate_percent"] == 50.0
        # All missing fields should have sensible defaults
        assert features["total_transactions"] == 0
        assert features["risk_metrics"]["max_drawdown_percent"] == 0.0

    def test_filter_and_score_consistency(self) -> None:
        """Both scoring and filtering should agree on high-quality wallets."""
        strong_stats = {
            "wallet_address": "StrongWallet333333333333333333333333333333",
            "chain": "solana",
            "total_profit": 100000.0,
            "total_profit_usd": 100000.0,
            "win_rate": 75.0,
            "win_rate_percent": 75.0,
            "total_trades": 500,
            "trades_7d": 80,
            "trades_30d": 350,
            "avg_holding_time": 48.0,
            "max_drawdown": 25.0,
            "portfolio_value": 50000.0,
            "balance_usd": 10000.0,
            "first_seen_at": "2024-01-01T00:00:00Z",
            "diversification_index": 0.75,
            "mev_attacker": False,
            "dev_wallet": False,
            "sniper_detected": False,
            "bot_pattern_score": 5.0,
            "mev_usage_percent": 5.0,
            "pump_fun_interaction_percent": 40.0,
            "avg_position_sol": 5.0,
            "sharpe_ratio": 2.5,
            "sortino_ratio": 3.0,
            "single_token_concentration_percent": 20.0,
            "self_transfer_ratio_percent": 2.0,
            "inactive_days": 1,
            "wallet_age_days": 180,
            "volatility_30d": 0.2,
            "turbo_slippage_usage_percent": 10.0,
            "large_gambler_ratio_percent": 10.0,
            "stop_loss_trigger_rate_percent": 70.0,
            "trade_intervals_seconds": [3600.0 + i * 300 for i in range(80)],
            "trade_hours_of_day": [8, 9, 10, 11, 12, 13, 14, 15, 16] * 10,
            "fees_sol_list": [0.005 + i * 0.001 for i in range(80)],
        }

        # Field-name correction for filter_wallet
        filter_input = {**strong_stats, "win_rate_percent": strong_stats["win_rate"], "avg_holding_hours": strong_stats["avg_holding_time"], "total_profit_usd": strong_stats["total_profit"]}

        features = map_wallet_stats_to_features(strong_stats)
        score_result = score_wallet(features)
        # Strong wallet should score well
        assert score_result["total_score"] >= 70.0
        assert score_result["decision"] in ("copy", "watch")

        wallet_features = WalletFeatures.from_dict(filter_input)
        filter_result = filter_wallet(wallet_features)
        assert filter_result["decision"] in ("pass", "watch")
        assert filter_result["hard_rejected"] is False
        assert filter_result["score"] >= 80
