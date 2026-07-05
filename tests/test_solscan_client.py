from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from gmgn_monitor.solscan_client import SolscanClient, SolscanApiError


class TestSolscanClientInit:
    """Basic construction tests."""

    def test_init_with_key(self):
        client = SolscanClient(api_key="demo_key")
        assert client._api_key == "demo_key"

    def test_init_no_key(self):
        client = SolscanClient(api_key=None)
        assert client._api_key is None


class TestSolscanClientMethods:
    """Tests for public API methods (mocked at urllib level)."""

    @pytest.fixture
    def client(self):
        return SolscanClient(api_key="test_key")

    def _make_cm_response(self, data):
        mock = MagicMock()
        mock.read.return_value = json.dumps(data).encode("utf-8")
        mock.__enter__ = MagicMock(return_value=mock)
        mock.__exit__ = MagicMock(return_value=False)
        return mock

    @patch("gmgn_monitor.solscan_client.urllib.request.urlopen")
    def test_get_account_info(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            {"account": "wallet123", "lamports": 1500000, "owner": "system"}
        )

        result = client.get_account_info("wallet123")

        assert result["account"] == "wallet123"
        assert result["lamports"] == 1500000
        req = mock_urlopen.call_args[0][0]
        assert "wallet123" in req.full_url

    @patch("gmgn_monitor.solscan_client.urllib.request.urlopen")
    def test_get_account_info_with_token_in_url(self, mock_urlopen, client):
        """Verify API key is sent as query param when present."""
        mock_urlopen.return_value = self._make_cm_response(
            {"account": "wallet123"}
        )

        client.get_account_info("wallet123")
        req = mock_urlopen.call_args[0][0]
        assert "token=test_key" in req.full_url

    @patch("gmgn_monitor.solscan_client.urllib.request.urlopen")
    def test_get_account_transactions(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            [{"tx_hash": "tx1"}, {"tx_hash": "tx2"}]
        )

        result = client.get_account_transactions("wallet123", limit=10)

        assert len(result) == 2
        assert result[0]["tx_hash"] == "tx1"
        req = mock_urlopen.call_args[0][0]
        assert "limit=10" in req.full_url

    @patch("gmgn_monitor.solscan_client.urllib.request.urlopen")
    def test_get_account_transactions_dict_response(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            {"transactions": [{"tx_hash": "tx1"}]}
        )

        result = client.get_account_transactions("wallet123")
        assert len(result) == 1
        assert result[0]["tx_hash"] == "tx1"

    @patch("gmgn_monitor.solscan_client.urllib.request.urlopen")
    def test_get_token_accounts(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            [{"token_address": "token1", "amount": 100}]
        )

        result = client.get_token_accounts("wallet123")

        assert len(result) == 1
        assert result[0]["token_address"] == "token1"

    @patch("gmgn_monitor.solscan_client.urllib.request.urlopen")
    def test_get_token_accounts_dict_response(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            {"tokens": [{"token_address": "token1"}]}
        )

        result = client.get_token_accounts("wallet123")
        assert len(result) == 1


class TestSolscanErrorHandling:
    """Error-path coverage."""

    @pytest.fixture
    def client(self):
        return SolscanClient(api_key="test_key")

    @patch("gmgn_monitor.solscan_client.urllib.request.urlopen")
    def test_http_400_raises(self, mock_urlopen, client):
        from urllib.error import HTTPError

        mock_urlopen.side_effect = HTTPError(
            url="https://public-api.solscan.io/account/wallet123",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=BytesIO(b'{"message":"bad request"}'),
        )

        with pytest.raises(SolscanApiError) as exc_info:
            client.get_account_info("wallet123")
        assert exc_info.value.http_status == 400

    @patch("gmgn_monitor.solscan_client.urllib.request.urlopen")
    def test_http_500_raises(self, mock_urlopen, client):
        from urllib.error import HTTPError

        mock_urlopen.side_effect = HTTPError(
            url="https://public-api.solscan.io/account/wallet123",
            code=500,
            msg="Server Error",
            hdrs={},
            fp=BytesIO(b'{"message":"server error"}'),
        )

        with pytest.raises(SolscanApiError) as exc_info:
            client.get_account_info("wallet123")
        assert exc_info.value.http_status == 500

    @patch("gmgn_monitor.solscan_client.urllib.request.urlopen")
    def test_invalid_json_raises(self, mock_urlopen, client):
        mock_urlopen.return_value = MagicMock(
            read=MagicMock(return_value=b"not json"),
            __enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value=b"not json"))),
            __exit__=MagicMock(return_value=False),
        )

        with pytest.raises(SolscanApiError) as exc_info:
            client.get_account_info("wallet123")
        assert "Invalid JSON" in str(exc_info.value)

    @patch("gmgn_monitor.solscan_client.urllib.request.urlopen")
    def test_network_error_raises(self, mock_urlopen, client):
        from urllib.error import URLError

        mock_urlopen.side_effect = URLError("Connection refused")

        with pytest.raises(SolscanApiError) as exc_info:
            client.get_account_info("wallet123")
        assert "Network error" in str(exc_info.value)


class TestSolscanApiErrorObject:
    """Direct unit tests for the exception class."""

    def test_error_code_and_http_status(self):
        err = SolscanApiError("boom", http_status=400)
        assert err.http_status == 400
        assert str(err) == "boom"

    def test_error_defaults(self):
        err = SolscanApiError("oops")
        assert err.http_status is None

    def test_message_property(self):
        err = SolscanApiError("hello")
        assert err.message == "hello"
