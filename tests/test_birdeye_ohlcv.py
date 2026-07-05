from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from gmgn_monitor.birdeye_client import BirdeyeClient, BirdeyeApiError


class TestBirdeyeOhlcvNormalization:
    """Tests for Birdeye OHLCV response normalization."""

    @pytest.fixture
    def client(self) -> BirdeyeClient:
        return BirdeyeClient(api_key="test_key")

    def _make_cm_response(self, data):
        mock = MagicMock()
        mock.read.return_value = json.dumps(data).encode("utf-8")
        mock.__enter__ = MagicMock(return_value=mock)
        mock.__exit__ = MagicMock(return_value=False)
        return mock

    @patch("gmgn_monitor.birdeye_client.urllib.request.urlopen")
    def test_get_token_ohlcv_list_format(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            [{"o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 1000, "unixTime": 1700000000}]
        )
        result = client.get_token_ohlcv("token123", timeframe="1H", limit=5, chain="sol")
        assert len(result) == 1
        assert result[0]["open"] == 1.0
        assert result[0]["high"] == 2.0
        assert result[0]["low"] == 0.5
        assert result[0]["close"] == 1.5
        assert result[0]["volume"] == 1000.0
        assert result[0]["timestamp"] == "2023-11-14T22:13:20Z"

    @patch("gmgn_monitor.birdeye_client.urllib.request.urlopen")
    def test_get_token_ohlcv_nested_data_items(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            {
                "success": True,
                "data": {
                    "items": [
                        {"unixTime": 1700000000, "open": 100, "high": 105, "low": 98, "close": 102, "volume": 50000}
                    ]
                }
            }
        )
        result = client.get_token_ohlcv("token123", timeframe="1H", limit=5, chain="sol")
        assert len(result) == 1
        assert result[0]["open"] == 100

    @patch("gmgn_monitor.birdeye_client.urllib.request.urlopen")
    def test_get_token_ohlcv_short_keys(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            {"success": True, "data": [{"o": 2, "h": 3, "l": 1, "c": 2.5, "v": 2000, "unixTime": 1700000000}]}
        )
        result = client.get_token_ohlcv("token123", timeframe="1H", limit=5, chain="sol")
        assert len(result) == 1
        assert result[0]["open"] == 2.0
        assert result[0]["high"] == 3.0
        assert result[0]["low"] == 1.0
        assert result[0]["close"] == 2.5
        assert result[0]["volume"] == 2000.0

    @patch("gmgn_monitor.birdeye_client.urllib.request.urlopen")
    def test_get_token_ohlcv_unix_time(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            {"success": True, "data": [{"o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 1000, "unixTime": 1700000000}]}
        )
        result = client.get_token_ohlcv("token123", timeframe="1H", limit=5, chain="sol")
        assert len(result) == 1

    def test_normalize_ohlcv_empty(self, client):
        assert client._normalize_ohlcv([]) == []
        assert client._normalize_ohlcv({}) == []
        assert client._normalize_ohlcv(None) == []

    def test_normalize_ohlcv_direct_list(self, client):
        raw = [{"o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 1000, "unixTime": 1700000000}]
        result = client._normalize_ohlcv(raw)
        assert len(result) == 1
        assert result[0]["timestamp"]

    def test_normalize_ohlcv_data_list(self, client):
        raw = {"data": [{"o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 1000, "unixTime": 1700000000}]}
        result = client._normalize_ohlcv(raw)
        assert len(result) == 1

    def test_normalize_ohlcv_items_list(self, client):
        raw = {"items": [{"o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 1000, "unixTime": 1700000000}]}
        result = client._normalize_ohlcv(raw)
        assert len(result) == 1

    def test_normalize_ohlcv_nested_data_items(self, client):
        raw = {"data": {"items": [{"o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 1000, "unixTime": 1700000000}]}}
        result = client._normalize_ohlcv(raw)
        assert len(result) == 1

    def test_convert_ohlcv_response_unix_time(self, client):
        raw = {"o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 1000, "unixTime": 1700000000}
        result = client.convert_ohlcv_response(raw)
        assert result["timestamp"] == "2023-11-14T22:13:20Z"
        assert result["open"] == 1.0
        assert result["high"] == 2.0
        assert result["low"] == 0.5
        assert result["close"] == 1.5
        assert result["volume"] == 1000.0

    def test_convert_ohlcv_response_short_keys(self, client):
        raw = {"o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 1000, "unixTime": 1700000000}
        result = client.convert_ohlcv_response(raw)
        assert result["open"] == 1.0
        assert result["high"] == 2.0
        assert result["low"] == 0.5
        assert result["close"] == 1.5
        assert result["volume"] == 1000.0

    def test_convert_ohlcv_response_full_keys(self, client):
        raw = {"open": 100, "high": 105, "low": 98, "close": 102, "volume": 50000, "unixTime": 1700000000}
        result = client.convert_ohlcv_response(raw)
        assert result["open"] == 100.0
        assert result["high"] == 105.0
        assert result["low"] == 98.0
        assert result["close"] == 102.0
        assert result["volume"] == 50000.0

    def test_convert_ohlcv_response_string_values(self, client):
        raw = {"open": "100.5", "high": "105.2", "low": "98.1", "close": "102.0", "volume": "50000", "unixTime": 1700000000}
        result = client.convert_ohlcv_response(raw)
        assert result["open"] == 100.5
        assert result["high"] == 105.2
        assert result["low"] == 98.1
        assert result["close"] == 102.0
        assert result["volume"] == 50000.0

    def test_convert_ohlcv_response_missing_fields(self, client):
        raw = {"unixTime": 1700000000}
        result = client.convert_ohlcv_response(raw)
        assert result["open"] == 0.0
        assert result["high"] == 0.0
        assert result["low"] == 0.0
        assert result["close"] == 0.0
        assert result["volume"] == 0.0
        assert result["timestamp"] == "2023-11-14T22:13:20Z"

    def test_convert_ohlcv_response_timestamp_string(self, client):
        raw = {"o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 1000, "timestamp": "2024-01-01T00:00:00Z"}
        result = client.convert_ohlcv_response(raw)
        assert result["timestamp"] == "2024-01-01T00:00:00Z"

    # Removed broken test with missing mock_urlopen fixture


class TestBirdeyeHistoryOhlcv:
    """Tests for the new get_token_history_ohlcv method."""

    @pytest.fixture
    def client(self) -> BirdeyeClient:
        return BirdeyeClient(api_key="test_key")

    def _make_cm_response(self, data):
        mock = MagicMock()
        mock.read.return_value = json.dumps(data).encode("utf-8")
        mock.__enter__ = MagicMock(return_value=mock)
        mock.__exit__ = MagicMock(return_value=False)
        return mock

    @patch("gmgn_monitor.birdeye_client.urllib.request.urlopen")
    def test_get_token_history_ohlcv_success(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            {
                "success": True,
                "data": {
                    "items": [
                        {"unixTime": 1700000000, "open": 100, "high": 105, "low": 98, "close": 102, "volume": 50000}
                    ]
                }
            }
        )
        result = client.get_token_history_ohlcv("token123", timeframe="1H", limit=5, chain="sol")
        assert len(result) == 1
        assert result[0]["open"] == 100.0
        assert result[0]["high"] == 105.0
        assert result[0]["low"] == 98.0
        assert result[0]["close"] == 102.0
        assert result[0]["volume"] == 50000.0

    @patch("gmgn_monitor.birdeye_client.urllib.request.urlopen")
    def test_get_token_history_ohlcv_api_error(self, mock_urlopen, client):
        from urllib.error import HTTPError
        mock_urlopen.side_effect = HTTPError(
            url="https://public-api.birdeye.so/defi/ohlcv",
            code=429,
            msg="Rate Limited",
            hdrs={},
            fp=BytesIO(b'{"message":"Rate Limited"}'),
        )
        with pytest.raises(BirdeyeApiError) as exc_info:
            client.get_token_history_ohlcv("token123", timeframe="1H", limit=5)
        assert "Rate Limited" in str(exc_info.value)

    @patch("gmgn_monitor.birdeye_client.urllib.request.urlopen")
    def test_get_token_history_ohlcv_network_error(self, mock_urlopen, client):
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("Connection refused")
        with pytest.raises(BirdeyeApiError) as exc_info:
            client.get_token_history_ohlcv("token123", timeframe="1H", limit=5)
        assert "Network error" in str(exc_info.value)

    @patch("gmgn_monitor.birdeye_client.urllib.request.urlopen")
    def test_get_token_history_ohlcv_invalid_json(self, mock_urlopen, client):
        mock_urlopen.return_value = MagicMock(
            read=MagicMock(return_value=b"not json"),
            __enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value=b"not json"))),
            __exit__=MagicMock(return_value=False),
        )
        with pytest.raises(BirdeyeApiError) as exc_info:
            client.get_token_history_ohlcv("token123", timeframe="1H", limit=5)
        assert "Invalid JSON" in str(exc_info.value)

    @patch("gmgn_monitor.birdeye_client.urllib.request.urlopen")
    def test_get_token_history_ohlcv_non_success(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            {"success": False, "message": "Invalid token address"}
        )
        with pytest.raises(BirdeyeApiError) as exc_info:
            client.get_token_history_ohlcv("token123", timeframe="1H", limit=5)
        assert "Invalid token address" in str(exc_info.value)


class TestBirdeyeOhlcvErrorHandling:
    """Error-path coverage for OHLCV methods."""

    @pytest.fixture
    def client(self) -> BirdeyeClient:
        return BirdeyeClient(api_key="test_key")

    def test_empty_response(self, client):
        result = client._normalize_ohlcv({})
        assert result == []

    def test_unexpected_response_format(self, client):
        result = client._normalize_ohlcv({"success": True, "data": {"unexpected": "value"}})
        assert result == []

    def test_mixed_items_in_response(self, client):
        raw = {
            "items": [
                {"o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 1000, "unixTime": 1700000000},
                "not a dict",
                {"o": 3, "h": 4, "l": 2, "c": 3.5, "v": 2000, "unixTime": 1700003600},
            ]
        }
        result = client._normalize_ohlcv(raw)
        # Only dict items should be processed
        assert len(result) == 2
        assert result[0]["open"] == 1.0
        assert result[1]["open"] == 3.0

    def test_invalid_timestamp_fallback(self, client):
        raw = {"o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 1000}
        result = client.convert_ohlcv_response(raw)
        # Missing timestamp falls back to current UTC time (ISO 8601 with Z suffix)
        assert result["timestamp"].endswith("Z")
        assert result["open"] == 1.0
