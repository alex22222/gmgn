from __future__ import annotations

import json
import time
import urllib.error
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from gmgn_monitor.gmgn_api_client import GmgnApiClient, GmgnApiError, _tls_context


class TestGmgnApiClientInit:
    """Basic construction tests."""

    def test_init_defaults(self):
        client = GmgnApiClient(api_key="secret123")
        assert client._api_key == "secret123"
        assert client._host == "https://openapi.gmgn.ai"

    def test_init_custom_host(self):
        client = GmgnApiClient(api_key="k", host="https://custom.example.com/")
        assert client._host == "https://custom.example.com"

    def test_init_host_no_trailing_slash(self):
        client = GmgnApiClient(api_key="k", host="https://custom.example.com")
        assert client._host == "https://custom.example.com"


class TestGmgnApiClientMethods:
    """Tests for the public API methods (mocked at urllib level)."""

    @pytest.fixture
    def client(self):
        return GmgnApiClient(api_key="test_key")

    def _make_response(self, data, code=0, message=""):
        return json.dumps({"code": code, "data": data, "message": message}).encode("utf-8")

    def _make_cm_response(self, data, code=0, message=""):
        """Build a mock context-manager response."""
        mock = MagicMock()
        mock.read.return_value = self._make_response(data, code, message)
        mock.__enter__ = MagicMock(return_value=mock)
        mock.__exit__ = MagicMock(return_value=False)
        return mock

    @patch("gmgn_monitor.gmgn_api_client.urllib.request.urlopen")
    def test_get_wallet_stats(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            {"addr1": {"total_profit": 100}}
        )

        result = client.get_wallet_stats(
            chain="sol", wallet_addresses=["addr1", "addr2"], period="7d"
        )

        assert result == {"addr1": {"total_profit": 100}}
        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        # urllib.Request normalises header names to lower case in the dict
        assert req.headers.get("X-apikey") == "test_key"
        assert "/v1/user/wallet_stats" in req.full_url
        assert "chain=sol" in req.full_url
        assert "addr1%2Caddr2" in req.full_url or "addr1,addr2" in req.full_url
        assert "period=7d" in req.full_url
        assert "timestamp=" in req.full_url
        assert "client_id=" in req.full_url

    @patch("gmgn_monitor.gmgn_api_client.urllib.request.urlopen")
    def test_get_wallet_activity(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            {"activities": [{"tx_hash": "abc"}]}
        )

        result = client.get_wallet_activity(
            chain="sol", wallet_address="addr1", limit=25
        )

        assert result["activities"][0]["tx_hash"] == "abc"
        req = mock_urlopen.call_args[0][0]
        assert "/v1/user/wallet_activity" in req.full_url
        assert "wallet_address=addr1" in req.full_url
        assert "limit=25" in req.full_url

    @patch("gmgn_monitor.gmgn_api_client.urllib.request.urlopen")
    def test_get_smartmoney(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            [{"wallet_address": "w1"}, {"wallet_address": "w2"}]
        )

        result = client.get_smartmoney(chain="sol", limit=50)
        assert len(result) == 2
        req = mock_urlopen.call_args[0][0]
        assert "/v1/user/smartmoney" in req.full_url
        assert "chain=sol" in req.full_url
        assert "limit=50" in req.full_url

    @patch("gmgn_monitor.gmgn_api_client.urllib.request.urlopen")
    def test_get_smartmoney_accepts_trade_filters(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            {"list": [{"maker": "w1"}]}
        )

        result = client.get_smartmoney(chain="sol", limit=50, side="buy")
        assert result["list"][0]["maker"] == "w1"
        req = mock_urlopen.call_args[0][0]
        assert "/v1/user/smartmoney" in req.full_url
        assert "side=buy" in req.full_url

    @patch("gmgn_monitor.gmgn_api_client.urllib.request.urlopen")
    def test_get_kol(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            {"list": [{"maker": "kol1"}]}
        )

        result = client.get_kol(chain="sol", limit=20, side="buy")
        assert result["list"][0]["maker"] == "kol1"
        req = mock_urlopen.call_args[0][0]
        assert "/v1/user/kol" in req.full_url
        assert "limit=20" in req.full_url
        assert "side=buy" in req.full_url

    @patch("gmgn_monitor.gmgn_api_client.urllib.request.urlopen")
    def test_get_token_top_traders(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            [{"wallet_address": "t1"}]
        )

        result = client.get_token_top_traders(
            chain="sol", token_address="token123", extra="yes"
        )
        assert len(result) == 1
        req = mock_urlopen.call_args[0][0]
        assert "/v1/market/token_top_traders" in req.full_url
        assert "address=token123" in req.full_url
        assert "token_address=token123" in req.full_url
        assert "extra=yes" in req.full_url

    @patch("gmgn_monitor.gmgn_api_client.urllib.request.urlopen")
    def test_get_trending_swaps(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            [{"rank": 1}]
        )

        result = client.get_trending_swaps(chain="sol", interval="24h")
        assert result[0]["rank"] == 1
        req = mock_urlopen.call_args[0][0]
        assert "/v1/market/rank" in req.full_url
        assert "interval=24h" in req.full_url

    @patch("gmgn_monitor.gmgn_api_client.urllib.request.urlopen")
    def test_get_token_signals(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response(
            [{"signal_type": 12}]
        )

        result = client.get_token_signals(chain="sol", groups=[{"signal_type": [12]}])

        assert result[0]["signal_type"] == 12
        req = mock_urlopen.call_args[0][0]
        assert "/v1/market/token_signal" in req.full_url
        assert req.get_method() == "POST"
        assert json.loads(req.data.decode("utf-8")) == {
            "chain": "sol",
            "groups": [{"signal_type": [12]}],
        }

    @patch("gmgn_monitor.gmgn_api_client.urllib.request.urlopen")
    def test_timeout_applied(self, mock_urlopen, client):
        mock_urlopen.return_value = self._make_cm_response({})
        client.get_smartmoney()
        assert mock_urlopen.call_args[1]["timeout"] == 30

    def test_tls_context_uses_certifi_when_default_cafile_missing(self):
        fake_paths = MagicMock(cafile=None)
        with patch("gmgn_monitor.gmgn_api_client.ssl.get_default_verify_paths", return_value=fake_paths):
            context = _tls_context()
        assert context is not None


class TestGmgnApiErrorHandling:
    """Error-path coverage."""

    @pytest.fixture
    def client(self):
        return GmgnApiClient(api_key="test_key")

    @patch("gmgn_monitor.gmgn_api_client.urllib.request.urlopen")
    def test_api_error_code_raises(self, mock_urlopen, client):
        mock_urlopen.return_value = MagicMock(
            read=MagicMock(return_value=json.dumps(
                {"code": 40001, "data": {}, "message": "bad request"}
            ).encode("utf-8")),
            __enter__=MagicMock(return_value=MagicMock()),
            __exit__=MagicMock(return_value=False),
        )
        # Override the nested read so it returns the same bytes
        inner = mock_urlopen.return_value.__enter__.return_value
        inner.read.return_value = json.dumps(
            {"code": 40001, "data": {}, "message": "bad request"}
        ).encode("utf-8")

        with pytest.raises(GmgnApiError) as exc_info:
            client.get_smartmoney()
        assert exc_info.value.code == 40001
        assert "bad request" in str(exc_info.value)

    @patch("gmgn_monitor.gmgn_api_client.urllib.request.urlopen")
    def test_http_400_raises_immediately(self, mock_urlopen, client):
        from urllib.error import HTTPError
        from io import BytesIO

        mock_urlopen.side_effect = HTTPError(
            url="https://openapi.gmgn.ai/v1/user/smartmoney",
            code=400,
            msg="Bad Request",
            hdrs={},
            fp=BytesIO(b'{"code":40001,"message":"bad request"}'),
        )

        with pytest.raises(GmgnApiError) as exc_info:
            client.get_smartmoney()
        assert exc_info.value.http_status == 400

    @patch("gmgn_monitor.gmgn_api_client.urllib.request.urlopen")
    def test_http_500_raises_immediately(self, mock_urlopen, client):
        from urllib.error import HTTPError
        from io import BytesIO

        mock_urlopen.side_effect = HTTPError(
            url="https://openapi.gmgn.ai/v1/user/smartmoney",
            code=500,
            msg="Server Error",
            hdrs={},
            fp=BytesIO(b'{"code":50001,"message":"server error"}'),
        )

        with pytest.raises(GmgnApiError) as exc_info:
            client.get_smartmoney()
        assert exc_info.value.http_status == 500

    @patch("gmgn_monitor.gmgn_api_client.urllib.request.urlopen")
    def test_invalid_json_raises(self, mock_urlopen, client):
        mock_urlopen.return_value = MagicMock(
            read=MagicMock(return_value=b"not json"),
            __enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value=b"not json"))),
            __exit__=MagicMock(return_value=False),
        )

        with pytest.raises(GmgnApiError) as exc_info:
            client.get_smartmoney()
        assert "Invalid JSON" in str(exc_info.value)

    @patch("gmgn_monitor.gmgn_api_client.urllib.request.urlopen")
    def test_network_error_raises(self, mock_urlopen, client):
        from urllib.error import URLError

        mock_urlopen.side_effect = URLError("Connection refused")

        with pytest.raises(GmgnApiError) as exc_info:
            client.get_smartmoney()
        assert "Network error" in str(exc_info.value)

    @patch("gmgn_monitor.gmgn_api_client.time.sleep")
    @patch("gmgn_monitor.gmgn_api_client.urllib.request.urlopen")
    def test_network_error_retries_once(self, mock_urlopen, mock_sleep, client):
        from urllib.error import URLError

        mock_urlopen.side_effect = [
            URLError("temporary eof"),
            MagicMock(read=MagicMock(return_value=json.dumps({"code": 0, "data": [{"ok": True}], "message": ""}).encode("utf-8")), close=MagicMock()),
        ]

        result = client.get_smartmoney()

        assert result == [{"ok": True}]
        assert mock_urlopen.call_count == 2
        mock_sleep.assert_called_once()


class TestRateLimitRetry:
    """Rate-limit retry logic (max 1 retry)."""

    @pytest.fixture
    def client(self):
        return GmgnApiClient(api_key="test_key")

    def _make_cm_response(self, data, code=0, message=""):
        """Build a mock context-manager response."""
        mock = MagicMock()
        mock.read.return_value = json.dumps({"code": code, "data": data, "message": message}).encode("utf-8")
        mock.__enter__ = MagicMock(return_value=mock)
        mock.__exit__ = MagicMock(return_value=False)
        return mock

    @patch("gmgn_monitor.gmgn_api_client.time.sleep")
    @patch("gmgn_monitor.gmgn_api_client.urllib.request.urlopen")
    def test_rate_limit_retry_with_header(self, mock_urlopen, mock_sleep, client):
        from urllib.error import HTTPError
        from io import BytesIO

        future_ts = 9999999999.0
        error_response = HTTPError(
            url="https://openapi.gmgn.ai/v1/user/smartmoney",
            code=429,
            msg="Too Many Requests",
            hdrs={"x-ratelimit-reset": str(future_ts)},
            fp=BytesIO(b'{"code":42901,"message":"rate limit"}'),
        )
        success_response = self._make_cm_response(
            [{"wallet_address": "w1"}]
        )

        mock_urlopen.side_effect = [error_response, success_response]

        result = client.get_smartmoney()
        assert result == [{"wallet_address": "w1"}]
        assert mock_urlopen.call_count == 2
        # Should have slept at least once (wait_until + 1s buffer)
        assert mock_sleep.call_count == 1

    @patch("gmgn_monitor.gmgn_api_client.time.sleep")
    @patch("gmgn_monitor.gmgn_api_client.urllib.request.urlopen")
    def test_rate_limit_retry_without_header(self, mock_urlopen, mock_sleep, client):
        from urllib.error import HTTPError
        from io import BytesIO

        error_response = HTTPError(
            url="https://openapi.gmgn.ai/v1/user/smartmoney",
            code=429,
            msg="Too Many Requests",
            hdrs={},
            fp=BytesIO(b'{"code":42901,"message":"rate limit"}'),
        )
        success_response = self._make_cm_response(
            [{"wallet_address": "w1"}]
        )

        mock_urlopen.side_effect = [error_response, success_response]

        result = client.get_smartmoney()
        assert result == [{"wallet_address": "w1"}]
        assert mock_urlopen.call_count == 2
        assert mock_sleep.call_count == 1

    @patch("gmgn_monitor.gmgn_api_client.time.sleep")
    @patch("gmgn_monitor.gmgn_api_client.urllib.request.urlopen")
    def test_rate_limit_exceeds_max_retry(self, mock_urlopen, mock_sleep, client):
        from urllib.error import HTTPError
        from io import BytesIO

        error_response = HTTPError(
            url="https://openapi.gmgn.ai/v1/user/smartmoney",
            code=429,
            msg="Too Many Requests",
            hdrs={"x-ratelimit-reset": "9999999999"},
            fp=BytesIO(b'{"code":42901,"message":"rate limit"}'),
        )

        # Two consecutive 429s should exhaust the single retry
        mock_urlopen.side_effect = [error_response, error_response]

        with pytest.raises(GmgnApiError) as exc_info:
            client.get_smartmoney()
        assert exc_info.value.http_status == 429
        assert mock_urlopen.call_count == 2

    @patch("gmgn_monitor.gmgn_api_client.time.sleep")
    @patch("gmgn_monitor.gmgn_api_client.time.time")
    @patch("gmgn_monitor.gmgn_api_client.urllib.request.urlopen")
    def test_rate_limit_retry_rebuilds_timestamp(self, mock_urlopen, mock_time, mock_sleep, client):
        from urllib.error import HTTPError
        from io import BytesIO
        from urllib.parse import parse_qs, urlsplit

        mock_time.side_effect = [1_700_000_000, 1_700_000_000, 1_700_000_040]
        error_response = HTTPError(
            url="https://openapi.gmgn.ai/v1/user/smartmoney",
            code=429,
            msg="Too Many Requests",
            hdrs={"x-ratelimit-reset": "1700000030"},
            fp=BytesIO(b'{"code":42901,"message":"rate limit"}'),
        )
        mock_urlopen.side_effect = [error_response, self._make_cm_response([{"ok": True}])]

        result = client.get_smartmoney()

        assert result == [{"ok": True}]
        timestamps = [
            parse_qs(urlsplit(call.args[0].full_url).query)["timestamp"][0]
            for call in mock_urlopen.call_args_list
        ]
        assert timestamps == ["1700000000", "1700000040"]
        mock_sleep.assert_called_once()

    @patch("gmgn_monitor.gmgn_api_client.time.sleep")
    @patch("gmgn_monitor.gmgn_api_client.time.time")
    @patch("gmgn_monitor.gmgn_api_client.urllib.request.urlopen")
    def test_timestamp_expired_retries_with_fresh_signature(self, mock_urlopen, mock_time, mock_sleep):
        from urllib.parse import parse_qs, urlsplit

        class StampSigner:
            def sign(self, message: str) -> str:
                return "sig-" + message.rsplit(":", 1)[-1]

        client = GmgnApiClient(api_key="test_key")
        client._signer = StampSigner()
        mock_time.side_effect = [1_700_000_000, 1_700_000_050]
        mock_urlopen.side_effect = [
            MagicMock(
                read=MagicMock(return_value=json.dumps(
                    {"code": 40003, "data": {}, "message": "timestamp expired"}
                ).encode("utf-8")),
                close=MagicMock(),
            ),
            self._make_cm_response({"holdings": []}),
        ]

        result = client.get_wallet_holdings(chain="sol", wallet_address="addr1")

        assert result == {"holdings": []}
        requests = [call.args[0] for call in mock_urlopen.call_args_list]
        timestamps = [
            parse_qs(urlsplit(req.full_url).query)["timestamp"][0]
            for req in requests
        ]
        assert timestamps == ["1700000000", "1700000050"]
        assert requests[0].headers["X-signature"] == "sig-1700000000"
        assert requests[1].headers["X-signature"] == "sig-1700000050"
        mock_sleep.assert_called_once()


class TestGmgnApiErrorObject:
    """Direct unit tests for the exception class."""

    def test_error_code_and_http_status(self):
        err = GmgnApiError("boom", code=123, http_status=400)
        assert err.code == 123
        assert err.http_status == 400
        assert str(err) == "boom"

    def test_error_defaults(self):
        err = GmgnApiError("oops")
        assert err.code is None
        assert err.http_status is None
