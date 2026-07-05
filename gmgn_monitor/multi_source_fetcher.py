from __future__ import annotations

from typing import Any

from .helius_client import HeliusClient, HeliusApiError
from .birdeye_client import BirdeyeClient, BirdeyeApiError
from .solscan_client import SolscanClient, SolscanApiError


__all__ = [
    "MultiSourceFetcher",
    "SourceUnavailableError",
]


class SourceUnavailableError(Exception):
    """Raised when a requested data source is not available (no API key or disabled)."""


class MultiSourceFetcher:
    """Unified fetcher that queries multiple blockchain data sources and
    aggregates the results.

    Each source is queried independently; failures are logged as ``None``
    so that partial data can still be returned.  The caller can use
    :pyfunc:`source_priority.merge_wallet_data` to combine the raw
    responses into a single canonical record.
    """

    def __init__(
        self,
        config: dict[str, str | None] | None = None,
    ) -> None:
        """Initialise source clients from a config dict.

        Args:
            config: Mapping of source name → API key.  Supported keys:
                ``"helius"``, ``"birdeye"``, ``"solscan"``, ``"gmgn"``.
                A value of ``None`` disables that source.
        """
        config = config or {}
        self._config = config

        helius_key = config.get("helius")
        self._helius = HeliusClient(api_key=helius_key) if helius_key else None

        birdeye_key = config.get("birdeye")
        self._birdeye = BirdeyeClient(api_key=birdeye_key) if birdeye_key else None

        solscan_key = config.get("solscan")
        self._solscan = SolscanClient(api_key=solscan_key) if solscan_key else None

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def is_source_available(self, source: str) -> bool:
        """Return ``True`` if the named source is configured and ready.

        Supported source names: ``"helius"``, ``"birdeye"``, ``"solscan"``.
        """
        mapping = {
            "helius": self._helius is not None,
            "birdeye": self._birdeye is not None,
            "solscan": self._solscan is not None,
        }
        return mapping.get(source, False)

    # ------------------------------------------------------------------
    # Wallet-level fetch
    # ------------------------------------------------------------------

    def fetch_wallet_data(
        self,
        wallet_address: str,
        chain: str = "sol",
    ) -> dict[str, Any]:
        """Query all available sources for data about a single wallet.

        Returns a dict keyed by source name::

            {
                "helius":   { ... portfolio ... } or None,
                "birdeye":  None,  # if not configured
                "solscan":  { ... transactions ... } or None,
            }

        Args:
            wallet_address: Target wallet address.
            chain: Blockchain identifier (used for chain-specific sources).

        Returns:
            Mapping of source name → raw response or ``None``.
        """
        results: dict[str, Any] = {}

        if self._helius:
            try:
                results["helius"] = {
                    "portfolio": self._helius.get_wallet_portfolio(wallet_address),
                    "transactions": self._helius.get_wallet_transactions(wallet_address, limit=20),
                }
            except HeliusApiError as e:
                results["helius"] = {"error": str(e)}

        if self._birdeye:
            try:
                results["birdeye"] = {
                    "transactions": self._birdeye.get_wallet_transactions(wallet_address, chain=chain, limit=20),
                }
            except BirdeyeApiError as e:
                results["birdeye"] = {"error": str(e)}

        if self._solscan:
            try:
                results["solscan"] = {
                    "account_info": self._solscan.get_account_info(wallet_address),
                    "transactions": self._solscan.get_account_transactions(wallet_address, limit=20),
                    "token_accounts": self._solscan.get_token_accounts(wallet_address),
                }
            except SolscanApiError as e:
                results["solscan"] = {"error": str(e)}

        return results

    # ------------------------------------------------------------------
    # Token-level fetch
    # ------------------------------------------------------------------

    def cross_validate_price(
        self,
        token_address: str,
        chain: str = "sol",
    ) -> dict[str, Any]:
        """Fetch the token price from every available source and return
        all raw values side-by-side so the caller can compare or average.

        Args:
            token_address: Token mint / contract address.
            chain: Blockchain identifier.

        Returns:
            Mapping of source name → price dict or ``None``.
        """
        results: dict[str, Any] = {
            "birdeye": None,
            "helius": None,
            "solscan": None,
        }

        if self._birdeye:
            try:
                results["birdeye"] = self._birdeye.get_token_price(token_address, chain=chain)
            except BirdeyeApiError as e:
                results["birdeye"] = {"error": str(e)}

        # Helius and Solscan do not expose direct price endpoints; they remain None.

        return results

    def get_best_ohlcv(
        self,
        token_address: str,
        chain: str = "sol",
        timeframe: str = "1H",
        limit: int = 20,
    ) -> list[dict]:
        """Return OHLCV data from the first available source.

        Priority: Birdeye → empty list.

        Args:
            token_address: Token mint / contract address.
            chain: Blockchain identifier.
            timeframe: Candle interval.
            limit: Number of candles.

        Returns:
            A list of OHLCV dicts.
        """
        if self._birdeye:
            try:
                return self._birdeye.get_token_ohlcv(token_address, timeframe=timeframe, limit=limit, chain=chain)
            except BirdeyeApiError:
                return []
        return []
