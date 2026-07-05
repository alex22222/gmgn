from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


__all__ = [
    "SolscanClient",
    "SolscanApiError",
]


DEFAULT_TIMEOUT = 30  # seconds
DEFAULT_BASE = "https://public-api.solscan.io"


class SolscanApiError(Exception):
    """Raised when the Solscan API returns a non-success response.

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


class SolscanClient:
    """Python HTTP client for the Solscan public API.

    Uses **only** the Python standard library.  When an API key is
    provided it is sent via the ``token`` query parameter.  Without a
    key the client operates against the public (rate-limited) endpoints.
    """

    def __init__(
        self,
        api_key: str | None = None,
    ) -> None:
        self._api_key = api_key

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _request(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an HTTP GET request and return parsed JSON.

        Raises:
            SolscanApiError: On network failure, invalid JSON, or non-2xx
                HTTP status.
        """
        if not path.startswith("/"):
            path = "/" + path
        query: dict[str, str] = {}
        if self._api_key:
            query["token"] = self._api_key
        if params:
            query.update({k: str(v) for k, v in params.items()})
        qs = urllib.parse.urlencode(query)
        url = f"{DEFAULT_BASE}{path}"
        if qs:
            url = f"{url}?{qs}"

        request_headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        req = urllib.request.Request(url, headers=request_headers, method="GET")

        try:
            with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as response:
                body = response.read().decode("utf-8")
                parsed = json.loads(body)
        except urllib.error.HTTPError as e:
            try:
                error_body = e.read().decode("utf-8")
                error_parsed = json.loads(error_body)
                raise SolscanApiError(
                    error_parsed.get("message", f"HTTP {e.code}"),
                    http_status=e.code,
                ) from e
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise SolscanApiError(
                    f"HTTP {e.code}: {e.reason}",
                    http_status=e.code,
                ) from e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise SolscanApiError(
                f"Network error: {e}", http_status=None,
            ) from e
        except json.JSONDecodeError as e:
            raise SolscanApiError(
                f"Invalid JSON: {e}", http_status=None,
            ) from e

        return parsed

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    def get_account_info(self, wallet_address: str) -> dict[str, Any]:
        """Fetch account information for a wallet.

        Args:
            wallet_address: Solana wallet address.

        Returns:
            Parsed JSON payload with account metadata (balance, owner, etc.).
        """
        return self._request(
            f"/account/{wallet_address}",
        )

    def get_account_transactions(
        self,
        wallet_address: str,
        limit: int = 50,
    ) -> list[dict]:
        """Fetch recent transactions for a wallet.

        Args:
            wallet_address: Solana wallet address.
            limit: Maximum number of transactions to return.

        Returns:
            A list of transaction dicts.
        """
        result = self._request(
            f"/account/transactions",
            params={"address": wallet_address, "limit": limit},
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

    def get_token_accounts(self, wallet_address: str) -> list[dict]:
        """Fetch token accounts (SPL tokens) held by a wallet.

        Args:
            wallet_address: Solana wallet address.

        Returns:
            A list of token account dicts.
        """
        result = self._request(
            f"/account/tokens",
            params={"address": wallet_address},
        )
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            tokens = result.get("tokens")
            if isinstance(tokens, list):
                return tokens
            data = result.get("data")
            if isinstance(data, list):
                return data
        return []
