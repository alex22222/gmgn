from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gmgn_monitor.real_wallet_fetcher import RealWalletFetcher


class TestRealWalletFetcherRealisticMockMode:
    def test_realistic_mock_fallback(self) -> None:
        fetcher = RealWalletFetcher(api_key=None, chain="sol", mock_fallback=True, use_realistic_mock=True)
        assert fetcher._is_realistic_mock()
        wallets = fetcher.fetch_smartmoney_wallets(limit=5)
        assert len(wallets) == 5
        assert all(isinstance(w, dict) for w in wallets)
        assert all("wallet_address" in w for w in wallets)

    def test_realistic_mock_stats(self) -> None:
        fetcher = RealWalletFetcher(api_key=None, chain="sol", mock_fallback=True, use_realistic_mock=True)
        stats = fetcher.fetch_wallet_stats(["addr1", "addr2"])
        assert isinstance(stats, dict)
        assert "addr1" in stats
        assert "addr2" in stats
        assert stats["addr1"]["chain"] == "sol"
        assert "total_profit" in stats["addr1"]
        assert "win_rate" in stats["addr1"]

    def test_realistic_mock_features(self) -> None:
        fetcher = RealWalletFetcher(api_key=None, chain="sol", mock_fallback=True, use_realistic_mock=True)
        stats = fetcher.fetch_wallet_stats(["addr1"])
        features_list = fetcher.build_scored_features(stats)
        assert len(features_list) == 1
        assert features_list[0]["wallet_address"] == "addr1"
        assert "profit_metrics" in features_list[0]
        assert "risk_metrics" in features_list[0]
        assert "frequency_metrics" in features_list[0]

    def test_realistic_mock_run_fetch(self) -> None:
        fetcher = RealWalletFetcher(api_key=None, chain="sol", mock_fallback=True, use_realistic_mock=True)
        features_list = fetcher.run_fetch(batch_size=5)
        assert len(features_list) == 5
        for feat in features_list:
            assert "wallet_address" in feat
            assert "chain" in feat
            assert "profit_metrics" in feat

    def test_legacy_mock_when_realistic_false(self) -> None:
        fetcher = RealWalletFetcher(api_key=None, chain="sol", mock_fallback=True, use_realistic_mock=False)
        assert not fetcher._is_realistic_mock()
        stats = fetcher.fetch_wallet_stats(["addr1"])
        assert stats["addr1"]["win_rate"] == 68.5  # legacy static value

    def test_realistic_mock_activity(self) -> None:
        fetcher = RealWalletFetcher(api_key=None, chain="sol", mock_fallback=True, use_realistic_mock=True)
        activity = fetcher.fetch_wallet_activity("addr1", limit=10)
        assert activity["wallet_address"] == "addr1"
        assert "activities" in activity

    def test_realistic_mock_with_real_client_false(self) -> None:
        fetcher = RealWalletFetcher(api_key="real-key", chain="sol", use_realistic_mock=True)
        assert not fetcher._is_realistic_mock()
        assert fetcher._client is not None


class TestRealWalletFetcherMockMode:
    def test_fallback_when_no_api_key(self) -> None:
        fetcher = RealWalletFetcher(api_key=None, chain="sol", mock_fallback=True)
        assert fetcher._is_mock()
        wallets = fetcher.fetch_smartmoney_wallets(limit=5)
        assert len(wallets) == 5
        assert all(isinstance(w, dict) for w in wallets)
        assert all("wallet_address" in w for w in wallets)

    def test_no_fallback_when_mock_fallback_false(self) -> None:
        fetcher = RealWalletFetcher(api_key=None, chain="sol", mock_fallback=False)
        assert not fetcher._is_mock()
        with pytest.raises(RuntimeError):
            fetcher.fetch_smartmoney_wallets()

    def test_fetch_wallet_stats_in_mock_mode(self) -> None:
        fetcher = RealWalletFetcher(api_key=None, chain="sol", mock_fallback=True)
        stats = fetcher.fetch_wallet_stats(["addr1", "addr2"])
        assert isinstance(stats, dict)
        assert "addr1" in stats
        assert "addr2" in stats
        assert stats["addr1"]["chain"] == "sol"
        assert stats["addr1"]["total_profit"] > 0

    def test_fetch_wallet_activity_in_mock_mode(self) -> None:
        fetcher = RealWalletFetcher(api_key=None, chain="sol", mock_fallback=True)
        activity = fetcher.fetch_wallet_activity("addr1", limit=10)
        assert activity["wallet_address"] == "addr1"
        assert "activities" in activity

    def test_build_scored_features_from_mock_stats(self) -> None:
        fetcher = RealWalletFetcher(api_key=None, chain="sol", mock_fallback=True)
        stats = fetcher.fetch_wallet_stats(["addr1"])
        features_list = fetcher.build_scored_features(stats)
        assert len(features_list) == 1
        assert features_list[0]["wallet_address"] == "addr1"
        assert "profit_metrics" in features_list[0]
        assert "risk_metrics" in features_list[0]

    def test_run_fetch_end_to_end_mock(self) -> None:
        fetcher = RealWalletFetcher(api_key=None, chain="sol", mock_fallback=True)
        features_list = fetcher.run_fetch(batch_size=5)
        assert len(features_list) == 5
        for feat in features_list:
            assert "wallet_address" in feat
            assert "chain" in feat
            assert "profit_metrics" in feat

    def test_run_fetch_with_output_path(self, tmp_path: Path) -> None:
        fetcher = RealWalletFetcher(api_key=None, chain="sol", mock_fallback=True)
        output = tmp_path / "wallets.jsonl"
        features_list = fetcher.run_fetch(batch_size=3, output_path=str(output))
        assert len(features_list) == 3
        assert output.exists()
        lines = output.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3
        for line in lines:
            parsed = json.loads(line)
            assert "wallet_address" in parsed

    def test_unwrap_data(self) -> None:
        assert RealWalletFetcher._unwrap_data({"code": 0, "data": {"a": 1}}) == {"a": 1}
        assert RealWalletFetcher._unwrap_data({"a": 1}) == {"a": 1}
        assert RealWalletFetcher._unwrap_data([1, 2]) == [1, 2]

    def test_extract_wallet_list(self) -> None:
        assert RealWalletFetcher._extract_wallet_list([{"w": 1}]) == [{"w": 1}]
        assert RealWalletFetcher._extract_wallet_list({"data": [{"w": 1}]}) == [{"w": 1}]
        assert RealWalletFetcher._extract_wallet_list({"data": {"list": [{"w": 1}]}}) == [{"w": 1}]


class TestRealWalletFetcherWithMockClient:
    def test_fetch_smartmoney_wallets(self) -> None:
        mock_client = MagicMock()
        mock_client.get_smartmoney.return_value = [
            {"wallet_address": "addr1"},
            {"wallet_address": "addr2"},
        ]
        fetcher = RealWalletFetcher(api_key="real-key", chain="sol")
        fetcher._client = mock_client
        wallets = fetcher.fetch_smartmoney_wallets(limit=2)
        assert len(wallets) == 2
        mock_client.get_smartmoney.assert_called_once_with(chain="sol", limit=2)

    def test_fetch_wallet_stats(self) -> None:
        mock_client = MagicMock()
        mock_client.get_wallet_stats.return_value = {
            "addr1": {"total_profit": 1000, "win_rate": 50.0},
        }
        fetcher = RealWalletFetcher(api_key="real-key", chain="sol")
        fetcher._client = mock_client
        stats = fetcher.fetch_wallet_stats(["addr1"], period="7d")
        assert "addr1" in stats
        mock_client.get_wallet_stats.assert_called_once_with(
            chain="sol", wallet_addresses=["addr1"], period="7d"
        )

    def test_fetch_wallet_activity(self) -> None:
        mock_client = MagicMock()
        mock_client.get_wallet_activity.return_value = {
            "activities": [{"tx_hash": "abc"}],
        }
        fetcher = RealWalletFetcher(api_key="real-key", chain="sol")
        fetcher._client = mock_client
        activity = fetcher.fetch_wallet_activity("addr1", limit=20)
        assert "activities" in activity
        mock_client.get_wallet_activity.assert_called_once_with(
            chain="sol", wallet_address="addr1", limit=20
        )

    def test_fetch_smartmoney_trades(self) -> None:
        mock_client = MagicMock()
        mock_client.get_smartmoney.return_value = {
            "list": [{"maker": "addr1", "side": "buy"}, {"maker": "addr2", "side": "sell"}]
        }
        fetcher = RealWalletFetcher(api_key="real-key", chain="sol")
        fetcher._client = mock_client

        trades = fetcher.fetch_smartmoney_trades(limit=20, side="buy")

        assert trades == [{"maker": "addr1", "side": "buy"}]
        mock_client.get_smartmoney.assert_called_once_with(chain="sol", limit=20, side="buy")

    def test_fetch_kol_trades(self) -> None:
        mock_client = MagicMock()
        mock_client.get_kol.return_value = {
            "list": [{"maker": "kol1", "side": "buy"}, {"maker": "kol2", "side": "sell"}]
        }
        fetcher = RealWalletFetcher(api_key="real-key", chain="sol")
        fetcher._client = mock_client

        trades = fetcher.fetch_kol_trades(limit=10, side="buy")

        assert trades == [{"maker": "kol1", "side": "buy"}]
        mock_client.get_kol.assert_called_once_with(chain="sol", limit=10, side="buy")

    def test_fetch_token_top_traders_accepts_tag_and_sort(self) -> None:
        mock_client = MagicMock()
        mock_client.get_token_top_traders.return_value = {
            "list": [{"wallet_address": "smart1"}]
        }
        fetcher = RealWalletFetcher(api_key="real-key", chain="sol")
        fetcher._client = mock_client

        traders = fetcher.fetch_token_top_traders(
            "Token111",
            limit=20,
            tag="smart_degen",
            order_by="profit",
            direction="desc",
        )

        assert traders == [{"wallet_address": "smart1"}]
        mock_client.get_token_top_traders.assert_called_once_with(
            chain="sol",
            token_address="Token111",
            limit=20,
            tag="smart_degen",
            order_by="profit",
            direction="desc",
        )

    def test_fetch_market_signal_wallets_extracts_smart_degen_wallets(self) -> None:
        mock_client = MagicMock()
        mock_client.get_token_signals.return_value = [{
            "token_address": "Token111",
            "signal_type": 12,
            "trigger_at": 1783229266,
            "trigger_mc": 150000,
            "market_cap": 180000,
            "signal_times": 3,
            "data": {
                "symbol": "PUNK",
                "count": 2,
                "total_amount": 153.5,
                "smart_degen_wallets": [
                    {"address": "SmartA", "buy_timestamp": 1783229266, "buy_amount": 79.5},
                    {"address": "SmartB", "buy_timestamp": 1783229270, "buy_amount": 74.0},
                ],
            },
        }]
        fetcher = RealWalletFetcher(api_key="real-key", chain="sol")
        fetcher._client = mock_client

        wallets = fetcher.fetch_market_signal_wallets(signal_type=12, limit=10)

        assert [wallet["wallet_address"] for wallet in wallets] == ["SmartA", "SmartB"]
        assert wallets[0]["token_address"] == "Token111"
        assert wallets[0]["token_symbol"] == "PUNK"
        assert wallets[0]["signal_type"] == 12
        assert wallets[0]["signal_times"] == 3
        assert wallets[0]["tags"] == ["smart_degen", "market_signal_12"]
        mock_client.get_token_signals.assert_called_once_with(
            chain="sol",
            groups=[{"signal_type": [12]}],
        )

    def test_build_scored_features_skips_non_dict_stats(self) -> None:
        fetcher = RealWalletFetcher(api_key="real-key", chain="sol")
        stats = {
            "addr1": {"total_profit": 1000},
            "addr2": "not a dict",
        }
        features_list = fetcher.build_scored_features(stats)
        assert len(features_list) == 1
        assert features_list[0]["wallet_address"] == "addr1"

    def test_build_scored_features_empty_input(self) -> None:
        fetcher = RealWalletFetcher(api_key="real-key", chain="sol")
        assert fetcher.build_scored_features({}) == []
        assert fetcher.build_scored_features([]) == []

    def test_run_fetch_with_real_client(self) -> None:
        mock_client = MagicMock()
        mock_client.get_smartmoney.return_value = [
            {"wallet_address": "addr1"},
            {"wallet_address": "addr2"},
        ]
        mock_client.get_wallet_stats.return_value = {
            "addr1": {"total_profit": 1000, "win_rate": 50.0, "trades_7d": 20, "chain": "sol"},
            "addr2": {"total_profit": 2000, "win_rate": 60.0, "trades_7d": 30, "chain": "sol"},
        }
        fetcher = RealWalletFetcher(api_key="real-key", chain="sol")
        fetcher._client = mock_client
        features_list = fetcher.run_fetch(batch_size=2)
        assert len(features_list) == 2
        for feat in features_list:
            assert "wallet_address" in feat
            assert feat["chain"] == "sol"

    def test_run_fetch_with_output_path_real(self, tmp_path: Path) -> None:
        mock_client = MagicMock()
        mock_client.get_smartmoney.return_value = [
            {"wallet_address": "addr1"},
        ]
        mock_client.get_wallet_stats.return_value = {
            "addr1": {"total_profit": 1000, "win_rate": 50.0, "trades_7d": 20, "chain": "sol"},
        }
        fetcher = RealWalletFetcher(api_key="real-key", chain="sol")
        fetcher._client = mock_client
        output = tmp_path / "real.jsonl"
        features_list = fetcher.run_fetch(batch_size=1, output_path=str(output))
        assert len(features_list) == 1
        assert output.exists()

    def test_run_fetch_batches_large_list(self) -> None:
        mock_client = MagicMock()
        addresses = [f"addr{i}" for i in range(250)]
        mock_client.get_smartmoney.return_value = [
            {"wallet_address": a} for a in addresses
        ]
        # Return empty stats for all addresses
        mock_client.get_wallet_stats.return_value = {
            a: {"total_profit": 0, "win_rate": 0.0} for a in addresses
        }
        fetcher = RealWalletFetcher(api_key="real-key", chain="sol")
        fetcher._client = mock_client
        features_list = fetcher.run_fetch(batch_size=250)
        assert len(features_list) == 250
        # Should be called in batches (250 / 100 = 3 calls)
        assert mock_client.get_wallet_stats.call_count == 3

    def test_api_key_from_env(self) -> None:
        with patch.dict("os.environ", {"GMGN_API_KEY": "env-key"}):
            fetcher = RealWalletFetcher(chain="sol")
            assert fetcher._api_key == "env-key"
            assert fetcher._client is not None

    def test_api_key_from_arg_overrides_env(self) -> None:
        with patch.dict("os.environ", {"GMGN_API_KEY": "env-key"}):
            fetcher = RealWalletFetcher(api_key="arg-key", chain="sol")
            assert fetcher._api_key == "arg-key"
