from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_RATE_LIMIT = 2.0  # requests per second
DEFAULT_MAX_RETRIES = 5
DEFAULT_BACKOFF_BASE = 2.0  # seconds
DEFAULT_TIMEOUT = 30  # seconds

DEFAULT_HEADERS = {
    "User-Agent": "gmgn-monitor/0.1.0 (research-only)",
    "Accept": "application/json",
}


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

@dataclass
class RateLimiter:
    """Token-bucket style rate limiter enforcing a maximum QPS."""

    max_requests_per_second: float = DEFAULT_RATE_LIMIT
    _min_interval: float = field(init=False, repr=False)
    _last_request_time: float | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._min_interval = 1.0 / self.max_requests_per_second

    def acquire(self) -> None:
        """Block until the rate limit allows the next request."""
        now = time.time()
        if self._last_request_time is not None:
            elapsed = now - self._last_request_time
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()

    def time_since_last(self) -> float | None:
        """Return seconds since the last request, or *None* if never called."""
        if self._last_request_time is None:
            return None
        return time.time() - self._last_request_time


# ---------------------------------------------------------------------------
# Low-level fetch with retry
# ---------------------------------------------------------------------------

def fetch_with_retry(
    url: str,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_base: float = DEFAULT_BACKOFF_BASE,
    timeout: int = DEFAULT_TIMEOUT,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Fetch a URL and return the JSON response.

    Transient HTTP errors (429, 5xx) and network errors are retried with
    exponential backoff.  Non-retryable HTTP errors (4xx except 429) are
    raised immediately.
    """
    request_headers = dict(DEFAULT_HEADERS)
    if headers:
        request_headers.update(headers)

    req = urllib.request.Request(url, headers=request_headers)
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                body = response.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                last_error = e
                wait = backoff_base ** attempt
                time.sleep(wait)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_error = e
            wait = backoff_base ** attempt
            time.sleep(wait)
            continue
        except json.JSONDecodeError as e:
            raise ValueError(f"invalid JSON from {url}: {e}") from e

    raise ValueError(f"failed to fetch {url} after {max_retries} attempts: {last_error}")


# ---------------------------------------------------------------------------
# Wallet fetcher
# ---------------------------------------------------------------------------

class WalletFetcher:
    """GMGN wallet data fetcher with built-in rate limiting and retry logic.

    When *mock* is ``True``, the fetcher returns synthetic fixture data
    without making any network requests.  This is useful for testing and
    dry-run pipelines.

    Usage::

        fetcher = WalletFetcher(mock=True)
        wallets = fetcher.run_fetch(batch_size=100, output_path=Path("data/wallets.jsonl"))
    """

    def __init__(
        self,
        rate_limit: float = DEFAULT_RATE_LIMIT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        mock: bool = False,
    ):
        self.rate_limiter = RateLimiter(max_requests_per_second=rate_limit)
        self.max_retries = max_retries
        self.mock = mock

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    def fetch_url(self, url: str) -> dict[str, Any]:
        """Fetch a single URL respecting the rate limit and retry policy."""
        self.rate_limiter.acquire()
        return fetch_with_retry(url, max_retries=self.max_retries)

    def fetch_batch(self, urls: list[str]) -> list[dict[str, Any]]:
        """Fetch a list of URLs, returning one result dict per URL.

        Failed requests are recorded as ``{"success": False, "error": "...", "url": "..."}``
        so the caller can decide whether to abort or continue.
        """
        results: list[dict[str, Any]] = []
        for url in urls:
            try:
                result = self.fetch_url(url)
                result["success"] = True
                result["url"] = url
                results.append(result)
            except Exception as exc:
                results.append({"success": False, "error": str(exc), "url": url})
        return results

    def run_fetch(
        self,
        urls: list[str] | None = None,
        batch_size: int = 1000,
        output_path: Path | None = None,
    ) -> list[dict[str, Any]]:
        """Run the fetch pipeline and optionally write results to JSONL.

        Args:
            urls: Target URLs to fetch.  Required when *mock* is ``False``.
            batch_size: Number of wallets to fetch (mock) or batch size hint.
            output_path: If given, write the returned wallets as JSONL.

        Returns:
            A list of wallet dicts (or error dicts for network mode).
        """
        if self.mock:
            wallets = self._mock_wallets(count=batch_size)
        else:
            if not urls:
                raise ValueError("urls must be provided when not in mock mode")
            wallets = self.fetch_batch(urls)

        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("w", encoding="utf-8") as fh:
                for wallet in wallets:
                    fh.write(json.dumps(wallet, ensure_ascii=False) + "\n")

        return wallets

    # -------------------------------------------------------------------
    # Mock helpers
    # -------------------------------------------------------------------

    def _mock_wallets(self, count: int = 100) -> list[dict[str, Any]]:
        """Generate *count* synthetic wallet records that satisfy the
        candidate-pool criteria (e.g. 7-day trades between 10-500, profit >= $30K).
        """
        return [self._mock_wallet(i) for i in range(count)]

    def _mock_wallet(self, index: int) -> dict[str, Any]:
        """Generate a single mock wallet record."""
        return {
            "wallet_address": f"MockWallet{index:04d}111111111111111111111111111111111111",
            "chain": "solana",
            "first_seen_at": "2025-01-15T08:30:00Z",
            "last_active_at": "2025-07-03T12:00:00Z",
            "source": "gmgn_mock",
            "fetched_at": "2025-07-03T12:00:00Z",
            "total_trades_7d": 72,
            "total_trades_30d": 280,
            "winning_trades_30d": 192,
            "win_rate_30d": 68.5,
            "avg_investment_usd": 1500.0,
            "avg_profit_usd": 850.0,
            "total_profit_usd": 52000.0,
            "avg_holding_duration_hours": 36.5,
            "stablecoin_balance_usd": 2500.0,
            "portfolio_balance_usd": 15000.0,
        }

    def mock_trades(self, wallet_address: str, count: int = 50) -> list[dict[str, Any]]:
        """Generate synthetic trade records for a wallet."""
        return [self._mock_trade(wallet_address, i) for i in range(count)]

    def _mock_trade(self, wallet_address: str, index: int) -> dict[str, Any]:
        """Generate a single mock trade record."""
        direction = "buy" if index % 2 == 0 else "sell"
        return {
            "tx_hash": f"mock_tx_{wallet_address}_{index:04d}",
            "wallet_address": wallet_address,
            "chain": "solana",
            "timestamp": "2025-07-01T14:23:00Z",
            "token_address": f"MockToken{index:04d}1111111111111111111111111111111111111",
            "token_symbol": f"MOCK{index}",
            "direction": direction,
            "amount_token": 1000.0 + index,
            "amount_sol": 5.5 + index * 0.1,
            "price_usd": 5.50 + index * 0.01,
            "slippage_percent": 25.0,
            "fee_sol": 0.005,
            "priority_fee_sol": 0.02,
            "dex": "raydium",
            "program_id": "675kPX9MHTjS2zt1qfr1...",
            "is_mev_protected": True,
            "mev_protection_mode": "secure",
        }
