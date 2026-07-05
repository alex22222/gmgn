from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from gmgn_monitor.helius_client import HeliusClient, HeliusApiError


class TestHeliusClientInit:
    """Basic construction tests."""

    def test_init_defaults(self):
        client = HeliusClient(api_key="demo_key")
        assert client._api_key == "demo_key"
        assert client._network == "mainnet"
        assert client._rpc_base == "https://mainnet.helius-rpc.com/"

    def test_init_custom_network(self):
        client = HeliusClient(api_key="k", network="devnet")
        assert client._network == "devnet"
        assert client._rpc_base == "https://devnet.helius-rpc.com/"

    def test_init_no_key(self):
        client = HeliusClient(api_key=None)
        assert client._api_key is None


class TestHeliusClientMethods:
    """Tests for public API methods (mocked at urllib level)."""

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
    def test_get_wallet_portfolio(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            {"balances": [{"token": "SOL", "amount": 10.5}]}
        )

        result = client.get_wallet_portfolio("wallet123")

        assert result["balances"][0]["token"] == "SOL"
        req = mock_urlopen.call_args[0][0]
        assert "api-key=test_key" in req.full_url
        assert "wallet123" in req.full_url

    @patch("gmgn_monitor.helius_client.urllib.request.urlopen")
    def test_get_wallet_transactions(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            [{"signature": "tx1"}, {"signature": "tx2"}]
        )

        result = client.get_wallet_transactions("wallet123", limit=10)

        assert len(result) == 2
        assert result[0]["signature"] == "tx1"
        req = mock_urlopen.call_args[0][0]
        assert "limit=10" in req.full_url

    @patch("gmgn_monitor.helius_client.urllib.request.urlopen")
    def test_get_wallet_transactions_dict_response(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            {"transactions": [{"signature": "tx1"}]}
        )

        result = client.get_wallet_transactions("wallet123")
        assert len(result) == 1
        assert result[0]["signature"] == "tx1"

    @patch("gmgn_monitor.helius_client.urllib.request.urlopen")
    def test_get_token_holders(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            {"holders": [{"address": "h1", "amount": 1000}]}
        )

        result = client.get_token_holders("token123", limit=50)

        assert len(result) == 1
        assert result[0]["address"] == "h1"
        req = mock_urlopen.call_args[0][0]
        assert "mint=token123" in req.full_url
        assert "limit=50" in req.full_url

    @patch("gmgn_monitor.helius_client.urllib.request.urlopen")
    def test_get_token_metadata(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            {"name": "Mock Token", "symbol": "MOCK"}
        )

        result = client.get_token_metadata("token123")

        assert result["name"] == "Mock Token"


class TestHeliusErrorHandling:
    """Error-path coverage."""

    @pytest.fixture
    def client(self):
        return HeliusClient(api_key="test_key")

    @patch("gmgn_monitor.helius_client.urllib.request.urlopen")
    def test_http_400_raises(self, mock_urlopen, client):
        from urllib.error import HTTPError

        mock_urlopen.side_effect = HTTPError(
            url="https://api.helius.xyz/v0/tokens",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=BytesIO(b'{"message":"bad request"}'),
        )

        with pytest.raises(HeliusApiError) as exc_info:
            client.get_token_metadata("token123")
        assert exc_info.value.http_status == 400

    @patch("gmgn_monitor.helius_client.urllib.request.urlopen")
    def test_http_500_raises(self, mock_urlopen, client):
        from urllib.error import HTTPError

        mock_urlopen.side_effect = HTTPError(
            url="https://api.helius.xyz/v0/tokens",
            code=500,
            msg="Server Error",
            hdrs={},
            fp=BytesIO(b'{"message":"server error"}'),
        )

        with pytest.raises(HeliusApiError) as exc_info:
            client.get_token_metadata("token123")
        assert exc_info.value.http_status == 500

    @patch("gmgn_monitor.helius_client.urllib.request.urlopen")
    def test_invalid_json_raises(self, mock_urlopen, client):
        mock_urlopen.return_value = MagicMock(
            read=MagicMock(return_value=b"not json"),
            __enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value=b"not json"))),
            __exit__=MagicMock(return_value=False),
        )

        with pytest.raises(HeliusApiError) as exc_info:
            client.get_token_metadata("token123")
        assert "Invalid JSON" in str(exc_info.value)

    @patch("gmgn_monitor.helius_client.urllib.request.urlopen")
    def test_network_error_raises(self, mock_urlopen, client):
        from urllib.error import URLError

        mock_urlopen.side_effect = URLError("Connection refused")

        with pytest.raises(HeliusApiError) as exc_info:
            client.get_token_metadata("token123")
        assert "Network error" in str(exc_info.value)


class TestHeliusApiErrorObject:
    """Direct unit tests for the exception class."""

    def test_error_code_and_http_status(self):
        err = HeliusApiError("boom", http_status=400)
        assert err.http_status == 400
        assert str(err) == "boom"

    def test_error_defaults(self):
        err = HeliusApiError("oops")
        assert err.http_status is None

    def test_message_property(self):
        err = HeliusApiError("hello")
        assert err.message == "hello"

    def test_message_property_empty(self):
        err = HeliusApiError("")
        assert err.message == ""
