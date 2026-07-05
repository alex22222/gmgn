from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from gmgn_monitor.multi_source_fetcher import (
    MultiSourceFetcher,
    SourceUnavailableError,
)
from gmgn_monitor.helius_client import HeliusApiError
from gmgn_monitor.birdeye_client import BirdeyeApiError
from gmgn_monitor.solscan_client import SolscanApiError


class TestMultiSourceFetcherInit:
    """Construction and availability tests."""

    def test_empty_config_no_sources_available(self):
        fetcher = MultiSourceFetcher(config={})
        assert not fetcher.is_source_available("helius")
        assert not fetcher.is_source_available("birdeye")
        assert not fetcher.is_source_available("solscan")
        assert not fetcher.is_source_available("unknown")

    def test_all_sources_configured(self):
        fetcher = MultiSourceFetcher(config={
            "helius": "h-key",
            "birdeye": "b-key",
            "solscan": "s-key",
        })
        assert fetcher.is_source_available("helius")
        assert fetcher.is_source_available("birdeye")
        assert fetcher.is_source_available("solscan")

    def test_partial_config(self):
        fetcher = MultiSourceFetcher(config={"helius": "h-key"})
        assert fetcher.is_source_available("helius")
        assert not fetcher.is_source_available("birdeye")
        assert not fetcher.is_source_available("solscan")

    def test_none_values_disable_sources(self):
        fetcher = MultiSourceFetcher(config={"helius": None, "birdeye": "b-key"})
        assert not fetcher.is_source_available("helius")
        assert fetcher.is_source_available("birdeye")


class TestMultiSourceFetcherWallet:
    """Tests for fetch_wallet_data."""

    def _make_urlopen_dispatcher(self, responses_by_url_keyword):
        """Return a side_effect function that dispatches by URL keyword."""
        def dispatch(req, **kwargs):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            for keyword, payload in responses_by_url_keyword.items():
                if keyword in url:
                    mock = MagicMock()
                    mock.read.return_value = json.dumps(payload).encode("utf-8")
                    mock.__enter__ = MagicMock(return_value=mock)
                    mock.__exit__ = MagicMock(return_value=False)
                    return mock
            raise RuntimeError(f"Unexpected URL: {url}")
        return dispatch

    @patch("urllib.request.urlopen")
    def test_fetch_wallet_data_helius_and_solscan(self, mock_urlopen):
        dispatcher = self._make_urlopen_dispatcher({
            "api.helius.xyz": {"balances": [{"token": "SOL"}]},
            "public-api.solscan.io": {"account": "wallet123", "lamports": 1000},
        })
        mock_urlopen.side_effect = dispatcher

        fetcher = MultiSourceFetcher(config={
            "helius": "h-key",
            "solscan": "s-key",
        })
        result = fetcher.fetch_wallet_data("wallet123", chain="sol")

        assert "helius" in result
        assert "solscan" in result
        assert "birdeye" not in result
        assert result["helius"]["portfolio"]["balances"][0]["token"] == "SOL"
        assert result["solscan"]["account_info"]["account"] == "wallet123"

    @patch("urllib.request.urlopen")
    def test_fetch_wallet_data_helius_error(self, mock_urlopen):
        from urllib.error import HTTPError
        from io import BytesIO

        def dispatch(req, **kwargs):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "api.helius.xyz" in url:
                raise HTTPError(
                    url=url,
                    code=500,
                    msg="Server Error",
                    hdrs={},
                    fp=BytesIO(b'{"message":"helius error"}'),
                )
            raise RuntimeError(f"Unexpected URL: {url}")

        mock_urlopen.side_effect = dispatch

        fetcher = MultiSourceFetcher(config={"helius": "h-key"})
        result = fetcher.fetch_wallet_data("wallet123")

        assert "helius" in result
        assert "error" in result["helius"]
        assert "helius error" in result["helius"]["error"]

    @patch("urllib.request.urlopen")
    def test_fetch_wallet_data_birdeye_error(self, mock_urlopen):
        from urllib.error import HTTPError
        from io import BytesIO

        def dispatch(req, **kwargs):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            if "public-api.birdeye.so" in url:
                raise HTTPError(
                    url=url,
                    code=429,
                    msg="Too Many Requests",
                    hdrs={},
                    fp=BytesIO(b'{"message":"rate limited"}'),
                )
            raise RuntimeError(f"Unexpected URL: {url}")

        mock_urlopen.side_effect = dispatch

        fetcher = MultiSourceFetcher(config={"birdeye": "b-key"})
        result = fetcher.fetch_wallet_data("wallet123", chain="sol")

        assert "birdeye" in result
        assert "error" in result["birdeye"]


class TestMultiSourceFetcherToken:
    """Tests for token-level methods."""

    @patch("gmgn_monitor.birdeye_client.urllib.request.urlopen")
    def test_cross_validate_price_birdeye_only(self, mock_urlopen):
        mock_urlopen.return_value = MagicMock(
            read=MagicMock(return_value=json.dumps(
                {"success": True, "data": {"price": 1.5, "address": "token123"}}
            ).encode("utf-8")),
            __enter__=MagicMock(return_value=MagicMock(
                read=MagicMock(return_value=json.dumps(
                    {"success": True, "data": {"price": 1.5}}
                ).encode("utf-8"))
            )),
            __exit__=MagicMock(return_value=False),
        )
        # The mock above is tricky because of nested context manager; simplify
        def response(req, **kwargs):
            mock = MagicMock()
            mock.read.return_value = json.dumps({"success": True, "data": {"price": 1.5}}).encode("utf-8")
            mock.__enter__ = MagicMock(return_value=mock)
            mock.__exit__ = MagicMock(return_value=False)
            return mock

        mock_urlopen.side_effect = response

        fetcher = MultiSourceFetcher(config={"birdeye": "b-key"})
        result = fetcher.cross_validate_price("token123", chain="sol")

        assert result["birdeye"]["price"] == 1.5
        assert result["helius"] is None
        assert result["solscan"] is None

    def test_cross_validate_price_no_sources(self):
        fetcher = MultiSourceFetcher(config={})
        result = fetcher.cross_validate_price("token123")

        assert result["birdeye"] is None
        assert result["helius"] is None
        assert result["solscan"] is None

    @patch("gmgn_monitor.birdeye_client.urllib.request.urlopen")
    def test_get_best_ohlcv(self, mock_urlopen):
        def response(req, **kwargs):
            mock = MagicMock()
            mock.read.return_value = json.dumps({"success": True, "data": {"items": [{"o": 1, "c": 2}]}}).encode("utf-8")
            mock.__enter__ = MagicMock(return_value=mock)
            mock.__exit__ = MagicMock(return_value=False)
            return mock

        mock_urlopen.side_effect = response

        fetcher = MultiSourceFetcher(config={"birdeye": "b-key"})
        result = fetcher.get_best_ohlcv("token123", chain="sol", timeframe="1D", limit=10)

        assert len(result) == 1
        assert result[0]["open"] == 1.0

    def test_get_best_ohlcv_no_sources(self):
        fetcher = MultiSourceFetcher(config={})
        result = fetcher.get_best_ohlcv("token123")
        assert result == []

    @patch("gmgn_monitor.birdeye_client.urllib.request.urlopen")
    def test_get_best_ohlcv_birdeye_error(self, mock_urlopen):
        from urllib.error import HTTPError
        from io import BytesIO

        mock_urlopen.side_effect = HTTPError(
            url="https://public-api.birdeye.so/public/history_ohlcv",
            code=500,
            msg="Error",
            hdrs={},
            fp=BytesIO(b'{"message":"err"}'),
        )

        fetcher = MultiSourceFetcher(config={"birdeye": "b-key"})
        result = fetcher.get_best_ohlcv("token123")
        assert result == []
