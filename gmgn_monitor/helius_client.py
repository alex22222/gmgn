from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


__all__ = [
    "HeliusClient",
    "HeliusApiError",
]


DEFAULT_TIMEOUT = 30  # seconds


class HeliusApiError(Exception):
    """Raised when the Helius API returns a non-success response.

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


class HeliusClient:
    """Python HTTP client for the Helius API.

    Uses **only** the Python standard library.  Supports both the
    RPC endpoint (``mainnet.helius-rpc.com``) and the Enhanced API
    (``api.helius.xyz/v0``).
    """

    def __init__(
        self,
        api_key: str | None = None,
        network: str = "mainnet",
    ) -> None:
        self._api_key = api_key
        self._network = network
        self._rpc_base = f"https://{network}.helius-rpc.com/"
        self._enhanced_base = "https://api.helius.xyz/v0"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _request(
        self,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Make an HTTP GET request and return parsed JSON.

        Raises:
            HeliusApiError: On network failure, invalid JSON, or non-2xx
                HTTP status.
        """
        request_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if headers:
            request_headers.update(headers)

        req = urllib.request.Request(url, headers=request_headers, method="GET")

        try:
            with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as response:
                body = response.read().decode("utf-8")
                parsed = json.loads(body)
        except urllib.error.HTTPError as e:
            try:
                error_body = e.read().decode("utf-8")
                error_parsed = json.loads(error_body)
                raise HeliusApiError(
                    error_parsed.get("message", f"HTTP {e.code}"),
                    http_status=e.code,
                ) from e
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise HeliusApiError(
                    f"HTTP {e.code}: {e.reason}",
                    http_status=e.code,
                ) from e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise HeliusApiError(
                f"Network error: {e}", http_status=None,
            ) from e
        except json.JSONDecodeError as e:
            raise HeliusApiError(
                f"Invalid JSON: {e}", http_status=None,
            ) from e

        return parsed

    def _rpc_url(self, method: str, params: dict[str, Any] | None = None) -> str:
        """Build a fully-qualified RPC URL with the API key."""
        query = {"api-key": self._api_key} if self._api_key else {}
        if params:
            query.update({k: str(v) for k, v in params.items()})
        qs = urllib.parse.urlencode(query)
        return f"{self._rpc_base}{method}?{qs}"

    def _enhanced_url(self, path: str, params: dict[str, Any] | None = None) -> str:
        """Build a fully-qualified Enhanced API URL with the API key."""
        if not path.startswith("/"):
            path = "/" + path
        query = {"api-key": self._api_key} if self._api_key else {}
        if params:
            query.update({k: str(v) for k, v in params.items()})
        qs = urllib.parse.urlencode(query)
        return f"{self._enhanced_base}{path}?{qs}"

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    def get_wallet_portfolio(self, wallet_address: str) -> dict[str, Any]:
        """Fetch the token portfolio for a single wallet.

        Uses the Enhanced API ``/addresses`` endpoint.

        Args:
            wallet_address: Solana wallet address.

        Returns:
            Parsed JSON payload containing token balances and metadata.
        """
        url = self._enhanced_url(
            f"/addresses/{wallet_address}/balances",
        )
        return self._request(url)

    def get_wallet_transactions(
        self,
        wallet_address: str,
        limit: int = 50,
    ) -> list[dict]:
        """Fetch recent transactions for a wallet.

        Uses the Enhanced API ``/addresses`` endpoint.

        Args:
            wallet_address: Solana wallet address.
            limit: Maximum number of transactions to return.

        Returns:
            A list of transaction dicts.
        """
        url = self._enhanced_url(
            f"/addresses/{wallet_address}/transactions",
            params={"limit": limit},
        )
        result = self._request(url)
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

    def get_token_holders(
        self,
        token_address: str,
        limit: int = 100,
    ) -> list[dict]:
        """Fetch top holders for a token.

        Uses the Enhanced API ``/token-holders`` endpoint.

        Args:
            token_address: Token mint address.
            limit: Maximum number of holders to return.

        Returns:
            A list of holder dicts.
        """
        url = self._enhanced_url(
            f"/token-holders",
            params={"mint": token_address, "limit": limit},
        )
        result = self._request(url)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            holders = result.get("holders")
            if isinstance(holders, list):
                return holders
            data = result.get("data")
            if isinstance(data, list):
                return data
        return []

    def get_token_price_history(
        self,
        token_address: str,
        from_timestamp: int | None = None,
        to_timestamp: int | None = None,
        limit: int = 168,
    ) -> list[dict]:
        """Fetch historical price data for a token via Helius Enhanced API.

        Helius doesn't have a dedicated OHLCV endpoint, but we can use
        transaction history to infer price movements or use the price API.

        Returns: ``[{timestamp, price}, ...]`` or ``[{timestamp, open, high, low, close, volume}, ...]``
        """
        # Try to get recent transactions and infer price from token transfers
        transactions = self.get_account_transactions_with_tokens(token_address, limit=limit)
        if transactions:
            return self.infer_price_from_transactions(token_address, transactions)
        return []

    def get_account_transactions_with_tokens(
        self,
        wallet_address: str,
        limit: int = 50,
    ) -> list[dict]:
        """Get transactions that include token transfers for price inference."""
        # Delegate to the existing get_wallet_transactions method
        return self.get_wallet_transactions(wallet_address, limit=limit)

    def infer_price_from_transactions(
        self,
        token_address: str,
        transactions: list[dict],
    ) -> list[dict]:
        """Infer price history from token transfer transactions.

        This is a fallback when no direct OHLCV API is available.
        Uses the timestamp of transactions as a proxy for price data.
        """
        from datetime import datetime, timezone

        price_points: list[dict] = []
        for tx in transactions:
            if not isinstance(tx, dict):
                continue
            timestamp = tx.get("timestamp", tx.get("blockTime", ""))
            if isinstance(timestamp, int):
                dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                ts_str = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            elif isinstance(timestamp, str):
                ts_str = timestamp
            else:
                continue

            # Use a placeholder price (Helius doesn't provide token prices directly)
            # In a real implementation, this would derive from swap amounts
            price_points.append({
                "timestamp": ts_str,
                "price": 0.0,
            })

        return price_points

    def get_token_metadata(self, token_address: str) -> dict[str, Any]:
        """Fetch metadata for a token.

        Uses the Enhanced API ``/tokens`` endpoint.

        Args:
            token_address: Token mint address.

        Returns:
            Parsed JSON payload with token metadata.
        """
        url = self._enhanced_url(
            f"/tokens",
            params={"mint": token_address},
        )
        return self._request(url)

    # ------------------------------------------------------------------
    # OHLCV / Price history methods
    # ------------------------------------------------------------------

    def get_token_price_history(
        self,
        token_address: str,
        from_timestamp: int | None = None,
        to_timestamp: int | None = None,
        limit: int = 168,
    ) -> list[dict]:
        """Fetch historical price data for a token via Helius Enhanced API.

        Helius does not expose a dedicated OHLCV endpoint, so this method
        tries the price history endpoint and falls back to transaction-based
        price inference when unavailable.

        Args:
            token_address: Token mint address.
            from_timestamp: Start unix timestamp (seconds). Defaults to
                ``limit`` hours ago.
            to_timestamp: End unix timestamp (seconds). Defaults to now.
            limit: Maximum number of data points to return.

        Returns:
            A list of price point dicts:
            ``[{timestamp: str, price: float}, ...]`` sorted by timestamp.
        """
        if not self._api_key:
            return []

        if to_timestamp is None:
            import time
            to_timestamp = int(time.time())
        if from_timestamp is None:
            from_timestamp = to_timestamp - (limit * 3600)

        # Try the Helius price history endpoint if available
        url = self._enhanced_url(
            f"/tokens/{token_address}/price-history",
            params={
                "from": from_timestamp,
                "to": to_timestamp,
                "limit": limit,
            },
        )
        try:
            parsed = self._request(url)
            if isinstance(parsed, list):
                return self._normalize_price_history(parsed)
            if isinstance(parsed, dict):
                items = parsed.get("items")
                if isinstance(items, list):
                    return self._normalize_price_history(items)
                data = parsed.get("data")
                if isinstance(data, list):
                    return self._normalize_price_history(data)
        except HeliusApiError:
            pass

        # Fallback: transaction-based price inference
        transactions = self.get_account_transactions_with_tokens(
            wallet_address=token_address,  # Use token as proxy for swap discovery
            limit=limit * 2,
        )
        return self.infer_price_from_transactions(token_address, transactions)

    def get_account_transactions_with_tokens(
        self,
        wallet_address: str,
        limit: int = 50,
    ) -> list[dict]:
        """Get transactions that include token transfers for price inference.

        Args:
            wallet_address: Solana wallet address to query.
            limit: Maximum number of transactions.

        Returns:
            A list of transaction dicts with token-transfer details.
        """
        if not self._api_key:
            return []

        url = self._enhanced_url(
            f"/addresses/{wallet_address}/transactions",
            params={"limit": limit},
        )
        try:
            parsed = self._request(url)
        except HeliusApiError:
            return []

        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            txs = parsed.get("transactions")
            if isinstance(txs, list):
                return txs
            data = parsed.get("data")
            if isinstance(data, list):
                return data
        return []

    def infer_price_from_transactions(
        self,
        token_address: str,
        transactions: list[dict],
    ) -> list[dict]:
        """Infer price history from token transfer transactions.

        This is a fallback when no direct OHLCV API is available.
        Uses the ratio of token amounts to SOL amounts in swap transactions
        to estimate historical price points.

        Args:
            token_address: Token mint address.
            transactions: List of transaction dicts from Helius.

        Returns:
            A list of price point dicts:
            ``[{timestamp: str, price: float}, ...]``.
        """
        from datetime import datetime, timezone

        price_points: list[dict] = []
        if not transactions:
            return price_points

        for tx in transactions:
            if not isinstance(tx, dict):
                continue

            timestamp_raw = tx.get("timestamp") or tx.get("blockTime")
            if timestamp_raw is None:
                continue

            try:
                if isinstance(timestamp_raw, int):
                    dt = datetime.fromtimestamp(timestamp_raw, tz=timezone.utc)
                    ts_str = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                else:
                    dt = datetime.fromisoformat(str(timestamp_raw).replace("Z", "+00:00"))
                    ts_str = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except (ValueError, OSError, TypeError):
                continue

            # Try to infer price from native transfers and token transfers
            price = self._infer_price_from_single_tx(token_address, tx)
            if price is not None and price > 0:
                price_points.append({"timestamp": ts_str, "price": round(price, 8)})

        # Sort by timestamp ascending
        price_points.sort(key=lambda p: p.get("timestamp", ""))
        return price_points

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _normalize_price_history(self, raw: list[dict]) -> list[dict]:
        """Normalize Helius price-history items to standard price points."""
        normalized: list[dict] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            ts_raw = item.get("timestamp") or item.get("unixTime") or item.get("time")
            price_raw = item.get("price") or item.get("value")
            if ts_raw is None or price_raw is None:
                continue
            try:
                if isinstance(ts_raw, int):
                    from datetime import datetime, timezone
                    ts_str = datetime.fromtimestamp(ts_raw, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                else:
                    from datetime import datetime, timezone
                    dt = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                    ts_str = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                price = float(price_raw)
                normalized.append({"timestamp": ts_str, "price": round(price, 8)})
            except (ValueError, TypeError, OSError):
                continue
        return normalized

    def _infer_price_from_single_tx(
        self, token_address: str, tx: dict
    ) -> float | None:
        """Infer token price from a single transaction dict.

        Looks for token transfers and native SOL transfers to estimate
        the exchange rate.  This is a rough heuristic and works best
        for tokens traded against SOL.
        """
        token_amount = None
        sol_amount = None

        # Check native transfers for SOL amount
        native_transfers = tx.get("nativeTransfers", [])
        if isinstance(native_transfers, list):
            for nt in native_transfers:
                if not isinstance(nt, dict):
                    continue
                amount = nt.get("amount")
                if amount is not None:
                    try:
                        # Native amount is in lamports
                        lamports = float(amount)
                        sol_amount = (sol_amount or 0.0) + (lamports / 1e9)
                    except (ValueError, TypeError):
                        continue

        # Check token transfers for this token
        token_transfers = tx.get("tokenTransfers", [])
        if isinstance(token_transfers, list):
            for tt in token_transfers:
                if not isinstance(tt, dict):
                    continue
                mint = tt.get("mint")
                if mint == token_address:
                    amount = tt.get("tokenAmount")
                    if amount is not None:
                        try:
                            token_amount = (token_amount or 0.0) + float(amount)
                        except (ValueError, TypeError):
                            continue
                    else:
                        raw_amount = tt.get("rawTokenAmount", {}).get("tokenAmount")
                        if raw_amount is not None:
                            try:
                                decimals = int(tt.get("rawTokenAmount", {}).get("decimals", 0))
                                token_amount = (token_amount or 0.0) + (float(raw_amount) / (10 ** decimals))
                            except (ValueError, TypeError):
                                continue

        # Also check events (swap events)
        events = tx.get("events", {})
        if isinstance(events, dict):
            swap = events.get("swap")
            if isinstance(swap, dict):
                native_input = swap.get("nativeInput")
                if isinstance(native_input, dict):
                    try:
                        lamports = float(native_input.get("amount", 0))
                        sol_amount = (sol_amount or 0.0) + (lamports / 1e9)
                    except (ValueError, TypeError):
                        pass
                token_outputs = swap.get("tokenOutputs", [])
                if isinstance(token_outputs, list):
                    for to in token_outputs:
                        if not isinstance(to, dict):
                            continue
                        if to.get("mint") == token_address:
                            try:
                                token_amount = (token_amount or 0.0) + float(to.get("tokenAmount", 0))
                            except (ValueError, TypeError):
                                continue

        if token_amount and sol_amount and token_amount > 0 and sol_amount > 0:
            return sol_amount / token_amount
        return None
