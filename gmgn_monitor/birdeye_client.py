from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


__all__ = [
    "BirdeyeClient",
    "BirdeyeApiError",
]


DEFAULT_TIMEOUT = 30  # seconds
DEFAULT_BASE = "https://public-api.birdeye.so"


class BirdeyeApiError(Exception):
    """Raised when the Birdeye API returns a non-success response.

    Attributes:
        message: Human-readable error description.
        http_status: HTTP status code (``None`` if not an HTTP error).
    """

    def __init__(
        self,
        message: str,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status

    @property
    def message(self) -> str:
        """Return the error message string."""
        return self.args[0] if self.args else ""


def _tls_context() -> ssl.SSLContext | None:
    default_cafile = ssl.get_default_verify_paths().cafile
    if default_cafile and Path(default_cafile).exists():
        return None
    try:
        import certifi
    except ImportError:
        return None
    return ssl.create_default_context(cafile=certifi.where())


def _birdeye_chain(chain: str) -> str:
    return {
        "sol": "solana",
        "eth": "ethereum",
    }.get(chain, chain)


class BirdeyeClient:
    """Python HTTP client for the Birdeye public API.

    Uses **only** the Python standard library.  When an API key is
    provided it is sent via the ``X-API-KEY`` header.  Without a key
    the client operates against the public (rate-limited) endpoints.
    """

    def __init__(
        self,
        api_key: str | None = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("BIRDEYE_API_KEY") or None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _request(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Make an HTTP GET request and return parsed JSON.

        Raises:
            BirdeyeApiError: On network failure, invalid JSON, or non-2xx
                HTTP status.
        """
        if not path.startswith("/"):
            path = "/" + path
        query = urllib.parse.urlencode(params) if params else ""
        url = f"{DEFAULT_BASE}{path}"
        if query:
            url = f"{url}?{query}"

        request_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self._api_key:
            request_headers["X-API-KEY"] = self._api_key
        if headers:
            request_headers.update(headers)

        req = urllib.request.Request(url, headers=request_headers, method="GET")

        kwargs: dict[str, Any] = {"timeout": DEFAULT_TIMEOUT}
        context = _tls_context()
        if context is not None:
            kwargs["context"] = context

        try:
            with urllib.request.urlopen(req, **kwargs) as response:
                body = response.read().decode("utf-8")
                parsed = json.loads(body)
        except urllib.error.HTTPError as e:
            try:
                error_body = e.read().decode("utf-8")
                error_parsed = json.loads(error_body)
                raise BirdeyeApiError(
                    error_parsed.get("message", f"HTTP {e.code}"),
                    http_status=e.code,
                ) from e
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise BirdeyeApiError(
                    f"HTTP {e.code}: {e.reason}",
                    http_status=e.code,
                ) from e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise BirdeyeApiError(
                f"Network error: {e}", http_status=None,
            ) from e
        except json.JSONDecodeError as e:
            raise BirdeyeApiError(
                f"Invalid JSON: {e}", http_status=None,
            ) from e

        # Birdeye wraps public responses in {success, data}
        if isinstance(parsed, dict) and "success" in parsed:
            if not parsed.get("success", True):
                raise BirdeyeApiError(
                    parsed.get("message", "Birdeye API error"),
                    http_status=None,
                )
            return parsed.get("data", {})

        return parsed

    # ------------------------------------------------------------------
    # Normalization helpers
    # ------------------------------------------------------------------

    def _normalize_ohlcv(self, raw: list[dict] | dict) -> list[dict]:
        """Normalize various Birdeye OHLCV response formats to a standard list of dicts.

        Standard format::

            [{timestamp, open, high, low, close, volume}, ...]

        Birdeye may return:

        - ``{ "data": { "items": [{unixTime, open, high, low, close, volume}] } }`` — nested
        - ``{ "items": [...] }`` — direct
        - ``[{unixTime, o, h, l, c, v}]`` — array with short keys

        Args:
            raw: Raw API response (list, dict, or nested dict).

        Returns:
            Normalised list of OHLCV dicts.
        """
        if not raw:
            return []
        if isinstance(raw, dict):
            items = raw.get("items")
            if isinstance(items, list):
                return [self.convert_ohlcv_response(item) for item in items if isinstance(item, dict)]
            data = raw.get("data")
            if isinstance(data, list):
                return [self.convert_ohlcv_response(item) for item in data if isinstance(item, dict)]
            if isinstance(data, dict):
                nested_items = data.get("items")
                if isinstance(nested_items, list):
                    return [self.convert_ohlcv_response(item) for item in nested_items if isinstance(item, dict)]
            return []
        if isinstance(raw, list):
            return [self.convert_ohlcv_response(item) for item in raw if isinstance(item, dict)]
        return []

    def convert_ohlcv_response(self, raw: dict) -> dict:
        """Convert a single Birdeye OHLCV item to the standard format.

        Handles:

        - ``unixTime`` (int seconds) → ISO 8601 timestamp string
        - Short keys (``o``, ``h``, ``l``, ``c``, ``v``) → full keys
        - Missing fields → ``None`` with sensible defaults

        Args:
            raw: A single raw OHLCV dict from Birdeye.

        Returns:
            Standard OHLCV dict.
        """
        # Timestamp normalisation
        ts = raw.get("unixTime")
        if ts is None:
            ts = raw.get("timestamp")
        if ts is None:
            ts = raw.get("time")

        if isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            timestamp = dt.isoformat().replace("+00:00", "Z")
        elif isinstance(ts, str):
            timestamp = str(ts)
        else:
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Price field normalisation (short keys → full keys)
        open_price = self._to_float(raw.get("o", raw.get("open")))
        high_price = self._to_float(raw.get("h", raw.get("high")))
        low_price = self._to_float(raw.get("l", raw.get("low")))
        close_price = self._to_float(raw.get("c", raw.get("close")))
        volume = self._to_float(raw.get("v", raw.get("volume")))

        return {
            "timestamp": timestamp,
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "volume": volume,
        }

    @staticmethod
    def _to_float(value: Any) -> float:
        """Safely convert a value to float, returning ``0.0`` on failure or None."""
        if value is None:
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    def get_token_price(
        self,
        token_address: str,
        chain: str = "sol",
    ) -> dict[str, Any]:
        """Fetch the current price for a token.

        Args:
            token_address: Token contract / mint address.
            chain: Blockchain identifier (default ``"sol"``).

        Returns:
            Parsed JSON payload with price information.
        """
        return self._request(
            "/defi/price",
            params={"address": token_address},
            headers={"x-chain": _birdeye_chain(chain)},
        )

    def get_token_ohlcv(
        self,
        token_address: str,
        timeframe: str = "1H",
        limit: int = 20,
        chain: str = "sol",
    ) -> list[dict]:
        """Fetch OHLCV candlestick data for a token.

        Args:
            token_address: Token contract / mint address.
            timeframe: Candle interval (e.g. ``"1H"``, ``"1D"``).
            limit: Number of candles to return.
            chain: Blockchain identifier (default ``"sol"``).

        Returns:
            A list of OHLCV dicts.
        """
        result = self._request(
            "/public/history_ohlcv",
            params={"address": token_address, "timeframe": timeframe, "limit": limit},
            headers={"x-chain": _birdeye_chain(chain)},
        )
        return self._normalize_ohlcv(result)

    def get_token_history_ohlcv(
        self,
        token_address: str,
        timeframe: str = "1H",
        limit: int = 168,
        chain: str = "sol",
    ) -> list[dict]:
        """Fetch historical OHLCV data using the Birdeye DEFI endpoint.

        Uses ``GET /defi/ohlcv`` with ``address``, ``type`` (timeframe),
        ``time_from`` and ``time_to`` parameters.  The time range is
        calculated from *limit* candles going backwards from now.

        Args:
            token_address: Token contract / mint address.
            timeframe: Candle interval (e.g. ``"1H"``, ``"15m"``).
            limit: Approximate number of candles to return.
            chain: Blockchain identifier (default ``"sol"``).

        Returns:
            A list of normalized OHLCV dicts.
        """
        import time

        now = int(time.time())
        tf_seconds: dict[str, int] = {
            "1m": 60,
            "3m": 180,
            "5m": 300,
            "15m": 900,
            "30m": 1800,
            "1H": 3600,
            "2H": 7200,
            "4H": 14400,
            "6H": 21600,
            "8H": 28800,
            "12H": 43200,
            "1D": 86400,
            "3D": 259200,
            "1W": 604800,
            "1M": 2592000,
        }
        interval = tf_seconds.get(timeframe, 3600)
        time_from = now - (limit * interval)
        time_to = now

        result = self._request(
            "/defi/ohlcv",
            params={
                "address": token_address,
                "type": timeframe,
                "time_from": time_from,
                "time_to": time_to,
            },
            headers={"x-chain": _birdeye_chain(chain)},
        )
        normalized = self._normalize_ohlcv(result)
        if normalized:
            return normalized

        # Fallback to the legacy endpoint
        result = self._request(
            "/public/history_ohlcv",
            params={"address": token_address, "timeframe": timeframe, "limit": limit},
            headers={"x-chain": _birdeye_chain(chain)},
        )
        return self._normalize_ohlcv(result)

    def get_wallet_transactions(
        self,
        wallet_address: str,
        chain: str = "sol",
        limit: int = 50,
    ) -> list[dict]:
        """Fetch recent token transactions for a wallet.

        Args:
            wallet_address: Wallet address.
            chain: Blockchain identifier (default ``"sol"``).
            limit: Maximum number of transactions.

        Returns:
            A list of transaction dicts.
        """
        result = self._request(
            "/public/wallet/txs",
            params={"wallet": wallet_address, "limit": limit},
            headers={"x-chain": _birdeye_chain(chain)},
        )
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            txs = result.get("transactions")
            if isinstance(txs, list):
                return txs
            data = result.get("data")
            if isinstance(data, list):
                return data
        return []

    def get_token_market_data(
        self,
        token_address: str,
        chain: str = "sol",
    ) -> dict[str, Any]:
        """Fetch aggregated market data for a token.

        Args:
            token_address: Token contract / mint address.
            chain: Blockchain identifier (default ``"sol"``).

        Returns:
            Parsed JSON payload with market data (volume, liquidity, etc.).
        """
        return self._request(
            "/public/market",
            params={"address": token_address},
            headers={"x-chain": _birdeye_chain(chain)},
        )
