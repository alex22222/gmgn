from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from gmgn_monitor.helius_client import HeliusClient, HeliusApiError
from gmgn_monitor.backtest_data_loader import BacktestDataLoader


class TestHeliusPriceHistory:
    """Tests for Helius price history methods."""

    @pytest.fixture
    def client(self):
        return HeliusClient(api_key="test_key")

    def _make_cm_response(self, data):
        mock = MagicMock()
        mock.read.return_value = json.dumps(data).encode("utf-8")
        mock.__enter__ = MagicMock(return_value=mock)
        mock.__exit__ = MagicMock(return_value=False)
        return mock

    @patch("gmgn_monitor.helius_client.urllib.request.urlopen")
    def test_get_token_price_history_list_response(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            [
                {"timestamp": "2025-01-01T00:00:00Z", "price": 1.5},
                {"timestamp": "2025-01-01T01:00:00Z", "price": 1.6},
            ]
        )

        result = client.get_token_price_history("token123", limit=10)

        assert len(result) == 2
        assert result[0]["timestamp"] == "2025-01-01T00:00:00Z"
        assert result[0]["price"] == 1.5
        assert result[1]["price"] == 1.6

    @patch("gmgn_monitor.helius_client.urllib.request.urlopen")
    def test_get_token_price_history_dict_response(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            {"items": [{"timestamp": "2025-01-01T00:00:00Z", "price": 2.0}]}
        )

        result = client.get_token_price_history("token123", limit=10)

        assert len(result) == 1
        assert result[0]["price"] == 2.0

    @patch("gmgn_monitor.helius_client.urllib.request.urlopen")
    def test_get_token_price_history_with_unix_time(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            [{"unixTime": 1704067200, "price": 3.0}]
        )

        result = client.get_token_price_history("token123", limit=10)

        assert len(result) == 1
        assert result[0]["timestamp"] == "2024-01-01T00:00:00Z"
        assert result[0]["price"] == 3.0

    @patch("gmgn_monitor.helius_client.urllib.request.urlopen")
    def test_get_token_price_history_empty_response(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response({"items": []})

        result = client.get_token_price_history("token123", limit=10)

        assert result == []

    @patch("gmgn_monitor.helius_client.urllib.request.urlopen")
    def test_get_token_price_history_api_error_fallback(self, mock_urlopen, client):
        from urllib.error import HTTPError

        mock_urlopen.side_effect = HTTPError(
            url="https://api.helius.xyz/v0/tokens/token123/price-history",
            code=500,
            msg="Server Error",
            hdrs={},
            fp=BytesIO(b'{"message":"server error"}'),
        )

        result = client.get_token_price_history("token123", limit=10)
        assert result == []

    @patch("gmgn_monitor.helius_client.urllib.request.urlopen")
    def test_get_token_price_history_no_key(self, mock_urlopen):
        client_no_key = HeliusClient(api_key=None)
        result = client_no_key.get_token_price_history("token123", limit=10)
        assert result == []

    @patch("gmgn_monitor.helius_client.urllib.request.urlopen")
    def test_get_account_transactions_with_tokens(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            [
                {
                    "signature": "tx1",
                    "timestamp": "2025-01-01T00:00:00Z",
                    "tokenTransfers": [
                        {"mint": "token123", "tokenAmount": 100.0}
                    ],
                }
            ]
        )

        result = client.get_account_transactions_with_tokens("wallet123", limit=10)

        assert len(result) == 1
        assert result[0]["signature"] == "tx1"

    @patch("gmgn_monitor.helius_client.urllib.request.urlopen")
    def test_get_account_transactions_with_tokens_no_key(self, mock_urlopen):
        client_no_key = HeliusClient(api_key=None)
        result = client_no_key.get_account_transactions_with_tokens("wallet123", limit=10)
        assert result == []

    def test_infer_price_from_transactions_with_swap_data(self):
        client = HeliusClient(api_key="test_key")
        transactions = [
            {
                "timestamp": "2025-01-01T00:00:00Z",
                "nativeTransfers": [{"amount": 1000000000}],
                "tokenTransfers": [{"mint": "token123", "tokenAmount": 10.0}],
            },
            {
                "timestamp": "2025-01-01T01:00:00Z",
                "nativeTransfers": [{"amount": 2000000000}],
                "tokenTransfers": [{"mint": "token123", "tokenAmount": 20.0}],
            },
        ]

        result = client.infer_price_from_transactions("token123", transactions)

        assert len(result) == 2
        # 1 SOL / 10 tokens = 0.1
        assert result[0]["price"] == 0.1
        # 2 SOL / 20 tokens = 0.1
        assert result[1]["price"] == 0.1

    def test_infer_price_from_transactions_with_events(self):
        client = HeliusClient(api_key="test_key")
        transactions = [
            {
                "timestamp": "2025-01-01T00:00:00Z",
                "events": {
                    "swap": {
                        "nativeInput": {"amount": 500000000},
                        "tokenOutputs": [{"mint": "token123", "tokenAmount": 5.0}],
                    }
                },
            }
        ]

        result = client.infer_price_from_transactions("token123", transactions)

        assert len(result) == 1
        # 0.5 SOL / 5 tokens = 0.1
        assert result[0]["price"] == 0.1

    def test_infer_price_from_transactions_insufficient_data(self):
        client = HeliusClient(api_key="test_key")
        transactions = [
            {
                "timestamp": "2025-01-01T00:00:00Z",
                "nativeTransfers": [],
                "tokenTransfers": [],
            }
        ]

        result = client.infer_price_from_transactions("token123", transactions)

        assert result == []

    def test_infer_price_from_transactions_with_raw_token_amount(self):
        client = HeliusClient(api_key="test_key")
        transactions = [
            {
                "timestamp": "2025-01-01T00:00:00Z",
                "nativeTransfers": [{"amount": 1000000000}],
                "tokenTransfers": [
                    {
                        "mint": "token123",
                        "rawTokenAmount": {
                            "tokenAmount": "1000000000",
                            "decimals": 9,
                        },
                    }
                ],
            }
        ]

        result = client.infer_price_from_transactions("token123", transactions)

        assert len(result) == 1
        # 1 SOL / 1 token = 1.0
        assert result[0]["price"] == 1.0

    def test_infer_price_from_transactions_with_block_time(self):
        client = HeliusClient(api_key="test_key")
        transactions = [
            {
                "blockTime": 1704067200,
                "nativeTransfers": [{"amount": 1000000000}],
                "tokenTransfers": [{"mint": "token123", "tokenAmount": 10.0}],
            }
        ]

        result = client.infer_price_from_transactions("token123", transactions)

        assert len(result) == 1
        assert result[0]["timestamp"] == "2024-01-01T00:00:00Z"


class TestHeliusBacktestDataLoaderIntegration:
    """Integration tests with BacktestDataLoader."""

    @patch("gmgn_monitor.helius_client.urllib.request.urlopen")
    def test_helius_fallback_in_loader(self, mock_urlopen):
        from gmgn_monitor.birdeye_client import BirdeyeApiError

        mock_urlopen.return_value = MagicMock(
            read=MagicMock(return_value=b'{"message":"server error"}'),
            __enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value=b'{"message":"server error"}'))),
            __exit__=MagicMock(return_value=False),
        )
        mock_urlopen.side_effect = None

        loader = BacktestDataLoader(
            birdeye_api_key="b-key", helius_api_key="h-key"
        )

        # Mock Birdeye to fail
        with patch.object(
            loader._birdeye_public,
            "get_token_history_ohlcv",
            side_effect=BirdeyeApiError("fail"),
        ):
            with patch.object(
                loader._birdeye_with_key,
                "get_token_history_ohlcv",
                side_effect=BirdeyeApiError("fail"),
            ):
                with patch.object(
                    loader._helius,
                    "get_token_price_history",
                    return_value=[
                        {"timestamp": "2025-01-01T00:00:00Z", "price": 2.0}
                    ],
                ):
                    data = loader.load_ohlcv("token123", limit=10)
                    assert len(data) > 0
                    assert "close" in data[0]

    def test_helius_no_key_skips_fallback(self):
        from gmgn_monitor.birdeye_client import BirdeyeApiError

        loader = BacktestDataLoader(birdeye_api_key="b-key")
        loader._cache.clear()  # avoid cache hits from previous tests
        assert loader._helius is None

        with patch.object(
            loader._birdeye_public,
            "get_token_history_ohlcv",
            side_effect=BirdeyeApiError("fail"),
        ):
            with patch.object(
                loader._birdeye_with_key,
                "get_token_history_ohlcv",
                side_effect=BirdeyeApiError("fail"),
            ):
                data = loader.load_ohlcv("token_no_helius", limit=10)
                # Should fall back to synthetic
                assert len(data) == 10
                assert "close" in data[0]
