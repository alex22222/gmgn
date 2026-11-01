from __future__ import annotations

import pytest

from gmgn_monitor.gmgn_data_mapper import (
    map_smartmoney_list_to_wallet_addresses,
    map_token_top_traders_to_wallet_addresses,
    map_wallet_stats_to_features,
)


class TestMapWalletStatsToFeatures:
    """Tests for mapping GMGN flat wallet stats to nested score_wallet features."""

    def _sample_stats(self) -> dict:
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

    def test_all_fields_present(self) -> None:
        stats = self._sample_stats()
        features = map_wallet_stats_to_features(stats)

        assert features["wallet_address"] == stats["wallet_address"]
        assert features["chain"] == stats["chain"]
        # total_transactions = total_trades or trades_30d or trades_7d
        assert features["total_transactions"] == stats["total_trades"]

        # Profit metrics
        pm = features["profit_metrics"]
        assert pm["win_rate_percent"] == 68.5
        assert pm["total_pnl_sol"] == pytest.approx(52000.0 / 150.0, rel=1e-4)
        assert pm["avg_profit_per_trade_sol"] == pytest.approx(52000.0 / 342 / 150.0, rel=1e-4)
        expected_pf = max(1.0, 68.5 / 30.0)
        assert pm["profit_factor"] == pytest.approx(expected_pf, rel=1e-4)
        assert pm["profit_loss_ratio"] == pm["profit_factor"]

        # Risk metrics — the mapper hard-codes these to 0.0
        rm = features["risk_metrics"]
        assert rm["max_drawdown_percent"] == 42.0
        assert rm["sharpe_ratio"] == 0.0
        assert rm["sortino_ratio"] == 0.0

        # Frequency metrics
        fm = features["frequency_metrics"]
        assert fm["trades_7d"] == 72
        assert fm["trades_30d"] == 280
        assert fm["avg_holding_hours"] == 36.5
        assert fm["avg_daily_trades"] == pytest.approx(280 / 30.0, rel=1e-4)

        # Portfolio metrics
        portm = features["portfolio_metrics"]
        assert portm["stablecoin_ratio_percent"] == pytest.approx(2500.0 / 15000.0 * 100.0, rel=1e-4)
        assert portm["diversification_index"] == 0.5

        # Behavior flags
        bf = features["behavior_flags"]
        assert bf["mev_attacker"] is False
        assert bf["dev_wallet"] is False

    def test_missing_fields_use_defaults(self) -> None:
        minimal = {}
        features = map_wallet_stats_to_features(minimal)

        assert features["wallet_address"] == ""
        assert features["chain"] == "solana"
        assert features["total_transactions"] == 0
        assert features["profit_metrics"]["win_rate_percent"] == 0.0
        assert features["risk_metrics"]["max_drawdown_percent"] == 0.0
        assert features["frequency_metrics"]["trades_7d"] == 0
        assert features["portfolio_metrics"]["diversification_index"] == 0.5
        assert features["behavior_flags"]["mev_attacker"] is False

    def test_maps_raw_gmgn_wallet_stats_shape(self) -> None:
        stats = {
            "wallet_address": "raw-wallet",
            "realized_profit": "49066.0315",
            "buy": 851,
            "sell": 1371,
            "pnl_stat": {
                "winrate": 0.4199134199,
                "avg_holding_period": 32759.8893,
            },
        }
        features = map_wallet_stats_to_features(stats)

        assert features["wallet_address"] == "raw-wallet"
        assert features["total_transactions"] == 2222
        assert features["trades_7d"] == 2222
        assert features["trades_30d"] == 2222
        assert features["win_rate_percent"] == pytest.approx(41.99, rel=1e-3)
        assert features["total_profit_usd"] == pytest.approx(49066.03, rel=1e-4)
        assert features["avg_holding_hours"] == pytest.approx(9.1, rel=1e-2)

    def test_explicit_zero_trade_window_is_preserved(self) -> None:
        stats = {"buy": 300, "sell": 300, "trades_7d": 0, "trades_30d": 600}
        features = map_wallet_stats_to_features(stats)
        assert features["trades_7d"] == 0
        assert features["trades_30d"] == 600
        assert features["total_transactions"] == 600

    def test_total_transactions_fallback_logic(self) -> None:
        # total_trades > 0 takes precedence
        stats = {"total_trades": 100, "trades_30d": 0}
        features = map_wallet_stats_to_features(stats)
        assert features["total_transactions"] == 100

        # trades_30d used when total_trades is 0
        stats2 = {"total_trades": 0, "trades_30d": 80}
        features2 = map_wallet_stats_to_features(stats2)
        assert features2["total_transactions"] == 80

        # trades_7d used when both are 0
        stats3 = {"total_trades": 0, "trades_30d": 0, "trades_7d": 10}
        features3 = map_wallet_stats_to_features(stats3)
        assert features3["total_transactions"] == 10

    def test_wallet_address_included(self) -> None:
        stats = {"wallet_address": "abc123"}
        features = map_wallet_stats_to_features(stats)
        assert features["wallet_address"] == "abc123"

    def test_chain_included(self) -> None:
        stats = {"chain": "base"}
        features = map_wallet_stats_to_features(stats)
        assert features["chain"] == "base"

    def test_first_seen_at_preserved(self) -> None:
        stats = {"first_seen_at": "2024-06-01T00:00:00Z"}
        features = map_wallet_stats_to_features(stats)
        assert features["first_seen_at"] == "2024-06-01T00:00:00Z"

    def test_sharpe_and_sortino_always_zero(self) -> None:
        # The mapper ignores sharpe_ratio / sortino_ratio from input
        stats = {"sharpe_ratio": 2.0, "sortino_ratio": 3.0}
        features = map_wallet_stats_to_features(stats)
        assert features["risk_metrics"]["sharpe_ratio"] == 0.0
        assert features["risk_metrics"]["sortino_ratio"] == 0.0

    def test_capital_metrics_derived_from_portfolio(self) -> None:
        stats = {"portfolio_value": 15000.0}
        features = map_wallet_stats_to_features(stats)
        expected_avg = round(15000.0 / 150.0 / 10.0, 4)
        assert features["capital_metrics"]["avg_position_sol"] == expected_avg
        assert features["capital_metrics"]["max_position_sol"] == round(15000.0 / 150.0, 4)

    def test_capital_metrics_read_from_input(self) -> None:
        stats = {"avg_position_sol": 3.0, "max_position_sol": 15.0}
        features = map_wallet_stats_to_features(stats)
        assert features["capital_metrics"]["avg_position_sol"] == 3.0
        assert features["capital_metrics"]["max_position_sol"] == 15.0

    def test_behavioral_metrics_always_zero(self) -> None:
        # The mapper ignores bot_pattern_score / mev_usage_percent from input
        stats = {"bot_pattern_score": 25.0, "mev_usage_percent": 30.0}
        features = map_wallet_stats_to_features(stats)
        assert features["behavioral_metrics"]["bot_pattern_score"] == 0.0
        assert features["behavioral_metrics"]["mev_usage_percent"] == 0.0

    def test_token_preference_empty_defaults(self) -> None:
        stats = {"pump_fun_interaction_percent": 80.0}
        features = map_wallet_stats_to_features(stats)
        assert features["token_preference"]["pump_fun_interaction_percent"] == 0.0
        assert features["token_preference"]["favorite_token_categories"] == []

    def test_diversification_index_always_default(self) -> None:
        stats = {"diversification_index": 0.75}
        features = map_wallet_stats_to_features(stats)
        assert features["portfolio_metrics"]["diversification_index"] == 0.5
        assert features["behavioral_metrics"]["diversification_index"] == 0.5

    def test_profit_factor_formula(self) -> None:
        # profit_factor = max(1.0, win_rate / 30.0) when win_rate > 0 else 1.0
        stats = {"win_rate": 60.0}
        features = map_wallet_stats_to_features(stats)
        expected = max(1.0, 60.0 / 30.0)
        assert features["profit_metrics"]["profit_factor"] == pytest.approx(expected, rel=1e-4)

    def test_profit_factor_with_zero_win_rate(self) -> None:
        stats = {"win_rate": 0.0}
        features = map_wallet_stats_to_features(stats)
        assert features["profit_metrics"]["profit_factor"] == 1.0

    def test_days_since_last_trade_included(self) -> None:
        stats = {"days_since_last_trade": 5.0}
        features = map_wallet_stats_to_features(stats)
        assert features["frequency_metrics"]["days_since_last_trade"] == 5.0

    def test_non_dict_input_raises(self) -> None:
        with pytest.raises(TypeError, match="wallet_stats must be a dict"):
            map_wallet_stats_to_features("not a dict")

    def test_mev_attacker_flag(self) -> None:
        stats = {"mev_attacker": True}
        features = map_wallet_stats_to_features(stats)
        assert features["behavior_flags"]["mev_attacker"] is True


class TestMapSmartmoneyListToWalletAddresses:
    def test_extracts_from_data_list(self) -> None:
        response = {
            "code": 0,
            "data": [
                {"wallet_address": "addr1", "rank": 1},
                {"wallet_address": "addr2", "rank": 2},
            ],
            "message": "",
        }
        addresses = map_smartmoney_list_to_wallet_addresses(response)
        assert addresses == ["addr1", "addr2"]

    def test_extracts_from_address_key(self) -> None:
        response = {
            "data": [
                {"address": "addr3"},
                {"address": "addr4"},
            ]
        }
        addresses = map_smartmoney_list_to_wallet_addresses(response)
        assert addresses == ["addr3", "addr4"]

    def test_empty_data(self) -> None:
        response = {"code": 0, "data": [], "message": ""}
        addresses = map_smartmoney_list_to_wallet_addresses(response)
        assert addresses == []

    def test_missing_data_key(self) -> None:
        response = {}
        addresses = map_smartmoney_list_to_wallet_addresses(response)
        assert addresses == []

    def test_non_list_data(self) -> None:
        response = {"data": {"wallet_address": "addr1"}}
        addresses = map_smartmoney_list_to_wallet_addresses(response)
        assert addresses == []

    def test_mixed_entries(self) -> None:
        response = {
            "data": [
                {"wallet_address": "addr1"},
                {"no_address": "x"},
                {"address": "addr2"},
            ]
        }
        addresses = map_smartmoney_list_to_wallet_addresses(response)
        assert addresses == ["addr1", "addr2"]

    def test_string_items(self) -> None:
        response = {"data": ["addr1", "addr2"]}
        addresses = map_smartmoney_list_to_wallet_addresses(response)
        assert addresses == ["addr1", "addr2"]

    def test_nested_dict_list(self) -> None:
        response = {"data": {"list": [{"wallet_address": "addr1"}]}}
        addresses = map_smartmoney_list_to_wallet_addresses(response)
        assert addresses == ["addr1"]


class TestMapTokenTopTradersToWalletAddresses:
    def test_extracts_from_data_list(self) -> None:
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

    def test_extracts_from_address_key(self) -> None:
        response = {
            "data": [
                {"address": "trader3"},
            ]
        }
        addresses = map_token_top_traders_to_wallet_addresses(response)
        assert addresses == ["trader3"]

    def test_extracts_from_account_address_key(self) -> None:
        response = {
            "data": [
                {"account_address": "trader4"},
            ]
        }
        addresses = map_token_top_traders_to_wallet_addresses(response)
        assert addresses == ["trader4"]

    def test_prefers_wallet_stats_address_over_account_address(self) -> None:
        response = {
            "data": [
                {"address": "wallet-stats-address", "account_address": "token-account-address"},
            ]
        }
        addresses = map_token_top_traders_to_wallet_addresses(response)
        assert addresses == ["wallet-stats-address"]

    def test_empty_data(self) -> None:
        response = {"code": 0, "data": [], "message": ""}
        addresses = map_token_top_traders_to_wallet_addresses(response)
        assert addresses == []

    def test_missing_data_key(self) -> None:
        response = {}
        addresses = map_token_top_traders_to_wallet_addresses(response)
        assert addresses == []

    def test_string_items(self) -> None:
        response = {"data": ["trader1", "trader2"]}
        addresses = map_token_top_traders_to_wallet_addresses(response)
        assert addresses == ["trader1", "trader2"]

    def test_nested_dict_list(self) -> None:
        response = {"data": {"list": [{"wallet_address": "trader1"}]}}
        addresses = map_token_top_traders_to_wallet_addresses(response)
        assert addresses == ["trader1"]
