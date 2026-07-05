from __future__ import annotations

import json
from pathlib import Path
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from gmgn_monitor.birdeye_client import BirdeyeClient, BirdeyeApiError


class TestBirdeyeClientInit:
    """Basic construction tests."""

    def test_init_with_key(self):
        client = BirdeyeClient(api_key="demo_key")
        assert client._api_key == "demo_key"

    def test_init_no_key(self):
        with patch.dict("os.environ", {"BIRDEYE_API_KEY": ""}, clear=False):
            client = BirdeyeClient(api_key=None)
        assert client._api_key is None

    def test_init_uses_env_key(self):
        with patch.dict("os.environ", {"BIRDEYE_API_KEY": "env-key"}, clear=False):
            client = BirdeyeClient(api_key=None)
        assert client._api_key == "env-key"

    def test_tls_context_uses_certifi_when_default_cafile_missing(self):
        fake_paths = MagicMock(cafile=None)
        fake_context = MagicMock()

        with patch("gmgn_monitor.birdeye_client.ssl.get_default_verify_paths", return_value=fake_paths), \
                patch("gmgn_monitor.birdeye_client.ssl.create_default_context", return_value=fake_context) as create_context:
            import certifi
            from gmgn_monitor.birdeye_client import _tls_context

            assert _tls_context() is fake_context
            create_context.assert_called_once_with(cafile=certifi.where())

    def test_tls_context_uses_system_default_when_cafile_exists(self):
        fake_paths = MagicMock(cafile=str(Path(__file__)))

        with patch("gmgn_monitor.birdeye_client.ssl.get_default_verify_paths", return_value=fake_paths):
            from gmgn_monitor.birdeye_client import _tls_context

            assert _tls_context() is None


class TestBirdeyeClientMethods:
    """Tests for public API methods (mocked at urllib level)."""

    @pytest.fixture
    def client(self):
        return BirdeyeClient(api_key="test_key")

    def _make_cm_response(self, data):
        mock = MagicMock()
        mock.read.return_value = json.dumps(data).encode("utf-8")
        mock.__enter__ = MagicMock(return_value=mock)
        mock.__exit__ = MagicMock(return_value=False)
        return mock

    @patch("gmgn_monitor.birdeye_client.urllib.request.urlopen")
    def test_get_token_price(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            {"success": True, "data": {"price": 1.23, "address": "token123"}}
        )

        result = client.get_token_price("token123", chain="sol")

        assert result["price"] == 1.23
        req = mock_urlopen.call_args[0][0]
        assert "/defi/price" in req.full_url
        assert "X-api-key" in req.headers
        assert req.headers["X-api-key"] == "test_key"
        assert "X-chain" in req.headers
        assert req.headers["X-chain"] == "solana"

    @patch("gmgn_monitor.birdeye_client.urllib.request.urlopen")
    def test_get_token_ohlcv(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            {"success": True, "data": {"items": [{"o": 1, "h": 2, "l": 0.5, "c": 1.5}]}}
        )

        result = client.get_token_ohlcv("token123", timeframe="1H", limit=5, chain="sol")

        assert len(result) == 1
        assert result[0]["open"] == 1.0
        assert result[0]["high"] == 2.0
        assert result[0]["low"] == 0.5
        assert result[0]["close"] == 1.5
        req = mock_urlopen.call_args[0][0]
        assert "timeframe=1H" in req.full_url
        assert "limit=5" in req.full_url

    @patch("gmgn_monitor.birdeye_client.urllib.request.urlopen")
    def test_get_token_ohlcv_list_response(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            [{"o": 1, "h": 2, "l": 0.5, "c": 1.5}]
        )

        result = client.get_token_ohlcv("token123")
        assert len(result) == 1

    @patch("gmgn_monitor.birdeye_client.urllib.request.urlopen")
    def test_get_wallet_transactions(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            {"success": True, "data": {"transactions": [{"tx": "abc"}]}}
        )

        result = client.get_wallet_transactions("wallet123", chain="sol", limit=10)

        assert len(result) == 1
        assert result[0]["tx"] == "abc"

    @patch("gmgn_monitor.birdeye_client.urllib.request.urlopen")
    def test_get_token_market_data(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            {"success": True, "data": {"volume24h": 1000000, "liquidity": 500000}}
        )

        result = client.get_token_market_data("token123", chain="sol")

        assert result["volume24h"] == 1000000
        assert result["liquidity"] == 500000

    @patch("gmgn_monitor.birdeye_client.urllib.request.urlopen")
    def test_unwrapped_response(self, mock_urlopen, client):
        """Test handling when API returns raw dict without success wrapper."""
        mock_urlopen.return_value = self._make_cm_response(
            {"price": 5.0}
        )

        result = client.get_token_price("token123")
        assert result["price"] == 5.0

    @patch("gmgn_monitor.birdeye_client.urllib.request.urlopen")
    def test_api_error_in_response(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            {"success": False, "message": "Rate limit exceeded"}
        )

        with pytest.raises(BirdeyeApiError) as exc_info:
            client.get_token_price("token123")
        assert "Rate limit exceeded" in str(exc_info.value)


class TestBirdeyeErrorHandling:
    """Error-path coverage."""

    @pytest.fixture
    def client(self):
        return BirdeyeClient(api_key="test_key")

    @patch("gmgn_monitor.birdeye_client.urllib.request.urlopen")
    def test_http_400_raises(self, mock_urlopen, client):
        from urllib.error import HTTPError

        mock_urlopen.side_effect = HTTPError(
            url="https://public-api.birdeye.so/public/price",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=BytesIO(b'{"message":"bad request"}'),
        )

        with pytest.raises(BirdeyeApiError) as exc_info:
            client.get_token_price("token123")
        assert exc_info.value.http_status == 400

    @patch("gmgn_monitor.birdeye_client.urllib.request.urlopen")
    def test_network_error_raises(self, mock_urlopen, client):
        from urllib.error import URLError

        mock_urlopen.side_effect = URLError("Connection refused")

        with pytest.raises(BirdeyeApiError) as exc_info:
            client.get_token_price("token123")
        assert "Network error" in str(exc_info.value)

    @patch("gmgn_monitor.birdeye_client.urllib.request.urlopen")
    def test_invalid_json_raises(self, mock_urlopen, client):
        mock_urlopen.return_value = MagicMock(
            read=MagicMock(return_value=b"not json"),
            __enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value=b"not json"))),
            __exit__=MagicMock(return_value=False),
        )

        with pytest.raises(BirdeyeApiError) as exc_info:
            client.get_token_price("token123")
        assert "Invalid JSON" in str(exc_info.value)


class TestBirdeyeApiErrorObject:
    """Direct unit tests for the exception class."""

    def test_error_code_and_http_status(self):
        err = BirdeyeApiError("boom", http_status=400)
        assert err.http_status == 400
        assert str(err) == "boom"

    def test_error_defaults(self):
        err = BirdeyeApiError("oops")
        assert err.http_status is None

    def test_message_property(self):
        err = BirdeyeApiError("hello")
        assert err.message == "hello"
