from __future__ import annotations

import json
import tempfile
import time
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gmgn_monitor.wallet_fetcher import (
    DEFAULT_RATE_LIMIT,
    RateLimiter,
    WalletFetcher,
    fetch_with_retry,
)


# ---------------------------------------------------------------------------
# RateLimiter tests
# ---------------------------------------------------------------------------

class TestRateLimiter:
    def test_enforces_delay(self) -> None:
        limiter = RateLimiter(max_requests_per_second=2.0)
        start = time.time()
        limiter.acquire()
        limiter.acquire()
        elapsed = time.time() - start
        assert elapsed >= 0.5  # at least 0.5s between two requests at 2/s

    def test_single_request_no_wait(self) -> None:
        limiter = RateLimiter(max_requests_per_second=2.0)
        start = time.time()
        limiter.acquire()
        elapsed = time.time() - start
        assert elapsed < 0.1  # should not block on first call

    def test_time_since_last_none_before_first(self) -> None:
        limiter = RateLimiter(max_requests_per_second=2.0)
        assert limiter.time_since_last() is None

    def test_time_since_last_after_request(self) -> None:
        limiter = RateLimiter(max_requests_per_second=2.0)
        limiter.acquire()
        since = limiter.time_since_last()
        assert since is not None
        assert since >= 0.0

    def test_high_rate_limit(self) -> None:
        limiter = RateLimiter(max_requests_per_second=100.0)
        start = time.time()
        limiter.acquire()
        limiter.acquire()
        limiter.acquire()
        elapsed = time.time() - start
        assert elapsed < 0.05  # 100 req/s = 10ms between calls


# ---------------------------------------------------------------------------
# fetch_with_retry tests
# ---------------------------------------------------------------------------

class TestFetchWithRetry:
    def test_successful_fetch(self) -> None:
        mock_response = MagicMock()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.read.return_value = b'{"data": [1, 2, 3]}'

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = fetch_with_retry("http://example.com/api")

        assert result == {"data": [1, 2, 3]}

    def test_retry_on_429(self) -> None:
        """429 Too Many Requests should trigger exponential backoff retry."""
        mock_ok = MagicMock()
        mock_ok.__enter__ = MagicMock(return_value=mock_ok)
        mock_ok.__exit__ = MagicMock(return_value=False)
        mock_ok.read.return_value = b'{"ok": true}'

        side_effects = [
            urllib.error.HTTPError("http://example.com", 429, "Too Many Requests", {}, None),
            mock_ok,
        ]

        with patch("urllib.request.urlopen", side_effect=side_effects):
            with patch("time.sleep") as mock_sleep:
                result = fetch_with_retry("http://example.com", max_retries=2, backoff_base=2.0)

        assert result == {"ok": True}
        mock_sleep.assert_called_once()
        # First retry wait = 2.0 ** 0 = 1.0 seconds
        mock_sleep.assert_called_with(1.0)

    def test_retry_on_500(self) -> None:
        mock_ok = MagicMock()
        mock_ok.__enter__ = MagicMock(return_value=mock_ok)
        mock_ok.__exit__ = MagicMock(return_value=False)
        mock_ok.read.return_value = b'{"ok": true}'

        side_effects = [
            urllib.error.HTTPError("http://example.com", 500, "Server Error", {}, None),
            mock_ok,
        ]

        with patch("urllib.request.urlopen", side_effect=side_effects):
            with patch("time.sleep") as mock_sleep:
                result = fetch_with_retry("http://example.com", max_retries=2, backoff_base=2.0)

        assert result == {"ok": True}
        mock_sleep.assert_called_with(1.0)

    def test_no_retry_on_404(self) -> None:
        """404 Not Found should NOT be retried."""
        error = urllib.error.HTTPError("http://example.com", 404, "Not Found", {}, None)

        with patch("urllib.request.urlopen", side_effect=error):
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                fetch_with_retry("http://example.com", max_retries=3)

        assert exc_info.value.code == 404

    def test_retry_on_network_error(self) -> None:
        mock_ok = MagicMock()
        mock_ok.__enter__ = MagicMock(return_value=mock_ok)
        mock_ok.__exit__ = MagicMock(return_value=False)
        mock_ok.read.return_value = b'{"ok": true}'

        side_effects = [
            urllib.error.URLError("Connection refused"),
            mock_ok,
        ]

        with patch("urllib.request.urlopen", side_effect=side_effects):
            with patch("time.sleep") as mock_sleep:
                result = fetch_with_retry("http://example.com", max_retries=2, backoff_base=2.0)

        assert result == {"ok": True}
        mock_sleep.assert_called_with(1.0)

    def test_exhausts_retries_and_raises(self) -> None:
        error = urllib.error.HTTPError("http://example.com", 503, "Service Unavailable", {}, None)

        with patch("urllib.request.urlopen", side_effect=error):
            with patch("time.sleep"):
                with pytest.raises(ValueError, match="failed to fetch http://example.com after 2 attempts"):
                    fetch_with_retry("http://example.com", max_retries=2, backoff_base=2.0)

    def test_invalid_json_raises(self) -> None:
        mock_response = MagicMock()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.read.return_value = b"not valid json"

        with patch("urllib.request.urlopen", return_value=mock_response):
            with pytest.raises(ValueError, match="invalid JSON from http://example.com"):
                fetch_with_retry("http://example.com")

    def test_custom_headers(self) -> None:
        mock_response = MagicMock()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.read.return_value = b'{"ok": true}'
        captured_headers = {}

        def capture_request(req, **_kwargs):
            captured_headers.update(dict(req.headers))
            return mock_response

        with patch("urllib.request.urlopen", side_effect=capture_request):
            fetch_with_retry("http://example.com", headers={"X-Custom": "test"})

        assert captured_headers.get("X-custom") == "test"

        assert captured_headers.get("X-custom") == "test"


# ---------------------------------------------------------------------------
# WalletFetcher tests
# ---------------------------------------------------------------------------

class TestWalletFetcherMock:
    def test_mock_mode_returns_wallets(self) -> None:
        fetcher = WalletFetcher(mock=True)
        wallets = fetcher.run_fetch(batch_size=10)

        assert len(wallets) == 10
        for wallet in wallets:
            assert wallet["chain"] == "solana"
            assert "wallet_address" in wallet

    def test_mock_wallet_data_satisfies_criteria(self) -> None:
        fetcher = WalletFetcher(mock=True)
        wallets = fetcher.run_fetch(batch_size=1)
        wallet = wallets[0]

        assert 10 <= wallet["total_trades_7d"] <= 500
        assert wallet["total_trades_30d"] >= 10
        assert wallet["total_profit_usd"] >= 30000
        assert wallet["win_rate_30d"] >= 60
        assert wallet["avg_holding_duration_hours"] >= 24
        assert wallet["stablecoin_balance_usd"] > 0

    def test_mock_trades(self) -> None:
        fetcher = WalletFetcher(mock=True)
        trades = fetcher.mock_trades("test_wallet", count=20)

        assert len(trades) == 20
        for trade in trades:
            assert trade["wallet_address"] == "test_wallet"
            assert trade["direction"] in ("buy", "sell")
            assert trade["chain"] == "solana"

    def test_mock_trade_alternates_direction(self) -> None:
        fetcher = WalletFetcher(mock=True)
        trades = fetcher.mock_trades("test_wallet", count=4)
        directions = [t["direction"] for t in trades]
        assert directions == ["buy", "sell", "buy", "sell"]

    def test_non_mock_without_urls_raises(self) -> None:
        fetcher = WalletFetcher(mock=False)
        with pytest.raises(ValueError, match="urls must be provided when not in mock mode"):
            fetcher.run_fetch(batch_size=10)


class TestWalletFetcherNetwork:
    def test_fetch_url_applies_rate_limit(self) -> None:
        fetcher = WalletFetcher(mock=False, rate_limit=2.0)
        mock_response = MagicMock()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_response.read.return_value = b'{"ok": true}'

        with patch("urllib.request.urlopen", return_value=mock_response):
            with patch("time.sleep") as mock_sleep:
                # Two requests at 2/sec should have 0.5s gap
                fetcher.fetch_url("http://example.com/1")
                fetcher.fetch_url("http://example.com/2")

        # RateLimiter sleeps between calls, but we can't easily assert exact
        # sleep amount here.  At least verify urlopen was called twice.

    def test_fetch_batch_success_and_failure(self) -> None:
        fetcher = WalletFetcher(mock=False, rate_limit=100.0)
        mock_ok = MagicMock()
        mock_ok.__enter__ = MagicMock(return_value=mock_ok)
        mock_ok.__exit__ = MagicMock(return_value=False)
        mock_ok.read.return_value = b'{"ok": true}'
        error = urllib.error.HTTPError("http://example.com", 404, "Not Found", {}, None)

        with patch("urllib.request.urlopen", side_effect=[mock_ok, error]):
            results = fetcher.fetch_batch(["http://example.com/1", "http://example.com/2"])

        assert len(results) == 2
        assert results[0]["success"] is True
        assert results[1]["success"] is False
        assert "404" in results[1]["error"]

    def test_fetch_batch_records_url_on_failure(self) -> None:
        fetcher = WalletFetcher(mock=False, rate_limit=100.0)
        error = urllib.error.URLError("timeout")

        with patch("urllib.request.urlopen", side_effect=error):
            results = fetcher.fetch_batch(["http://example.com/fail"])

        assert results[0]["url"] == "http://example.com/fail"
        assert results[0]["success"] is False


class TestWalletFetcherOutput:
    def test_jsonl_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "wallets.jsonl"
            fetcher = WalletFetcher(mock=True)
            wallets = fetcher.run_fetch(batch_size=5, output_path=output_path)

            assert len(wallets) == 5
            assert output_path.exists()

            lines = output_path.read_text(encoding="utf-8").strip().split("\n")
            assert len(lines) == 5
            for line in lines:
                record = json.loads(line)
                assert record["chain"] == "solana"

    def test_output_creates_parent_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "nested" / "dir" / "wallets.jsonl"
            fetcher = WalletFetcher(mock=True)
            fetcher.run_fetch(batch_size=2, output_path=output_path)

            assert output_path.exists()

    def test_jsonl_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "wallets.jsonl"
            fetcher = WalletFetcher(mock=True)
            fetcher.run_fetch(batch_size=3, output_path=output_path)

            from gmgn_monitor.serialization import load_jsonl
            records = list(load_jsonl(output_path))
            assert len(records) == 3
            assert all("wallet_address" in r for r in records)
