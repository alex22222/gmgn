from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .birdeye_client import BirdeyeApiError, BirdeyeClient
from .dexscreener import fetch_tokens_payload
from .portfolio_tracker import PortfolioTracker


__all__ = [
    "PriceSource",
    "PositionMonitor",
]

logger = logging.getLogger(__name__)
DEFAULT_PRICE_CACHE_TTL_SECONDS = 15.0
DEFAULT_BIRDEYE_RATE_LIMIT_COOLDOWN_SECONDS = 300.0


class PriceSource(Enum):
    """Supported price data sources for token valuation."""

    BIRDEYE = "birdeye"
    DEXSCREENER = "dexscreener"
    HELIUS = "helius"


class PositionMonitor:
    """Monitor open positions and update their current prices.

    Uses a price oracle (Birdeye by default) to fetch live token prices and
    keep the portfolio tracker up-to-date.
    """

    def __init__(
        self,
        birdeye_client: BirdeyeClient | None = None,
        price_cache_ttl_seconds: float = DEFAULT_PRICE_CACHE_TTL_SECONDS,
        birdeye_rate_limit_cooldown_seconds: float = DEFAULT_BIRDEYE_RATE_LIMIT_COOLDOWN_SECONDS,
    ) -> None:
        """Initialize the position monitor.

        Args:
            birdeye_client: Optional BirdeyeClient instance. If ``None``,
                a new client is created without an API key (public endpoints).
        """
        self._birdeye = birdeye_client or BirdeyeClient()
        self._price_cache_ttl_seconds = price_cache_ttl_seconds
        self._birdeye_rate_limit_cooldown_seconds = birdeye_rate_limit_cooldown_seconds
        self._price_cache: dict[tuple[str, str], tuple[float, float]] = {}
        self._birdeye_cooldown_until = 0.0

    # ------------------------------------------------------------------
    # Price fetching
    # ------------------------------------------------------------------

    def fetch_token_price(self, token_address: str, chain: str = "sol") -> float:
        """Fetch the current USD price for a token.

        Tries multiple common response keys to extract the price value.

        Args:
            token_address: Token contract / mint address.
            chain: Blockchain identifier (default ``"sol"``).

        Returns:
            Token price in USD, or ``0.0`` if the request fails.
        """
        cache_key = (chain, token_address)
        cached_price = self._cached_price(cache_key)
        if cached_price > 0:
            return cached_price

        if time.monotonic() < self._birdeye_cooldown_until:
            return self._fetch_and_cache_dexscreener_price(cache_key, token_address, chain)

        try:
            price_data = self._birdeye.get_token_price(token_address, chain)
        except BirdeyeApiError as e:
            if _is_rate_limit_error(e):
                self._birdeye_cooldown_until = (
                    time.monotonic() + self._birdeye_rate_limit_cooldown_seconds
                )
                logger.warning(
                    "Birdeye rate limited; cooling down price requests for %.0fs",
                    self._birdeye_rate_limit_cooldown_seconds,
                )
                return self._fetch_and_cache_dexscreener_price(cache_key, token_address, chain)
            logger.warning("Birdeye price fetch failed for %s: %s", token_address, e)
            return self._fetch_and_cache_dexscreener_price(cache_key, token_address, chain)
        except Exception as e:
            logger.warning("Birdeye price fetch failed for %s: %s", token_address, e)
            return self._fetch_and_cache_dexscreener_price(cache_key, token_address, chain)

        if not isinstance(price_data, dict):
            logger.warning("Unexpected Birdeye price response type for %s", token_address)
            return self._fetch_and_cache_dexscreener_price(cache_key, token_address, chain)

        # Try common price field names in order of likelihood
        for key in ("price", "value", "usd", "current_price", "price_usd", "data"):
            val = price_data.get(key)
            if val is not None:
                try:
                    price = float(val)
                    if price > 0:
                        self._store_price(cache_key, price)
                        return price
                except (TypeError, ValueError):
                    continue

        # Nested structures
        nested = price_data.get("data")
        if isinstance(nested, dict):
            for key in ("price", "value", "usd", "current_price", "price_usd"):
                val = nested.get(key)
                if val is not None:
                    try:
                        price = float(val)
                        if price > 0:
                            self._store_price(cache_key, price)
                            return price
                    except (TypeError, ValueError):
                        continue

        logger.warning("Could not extract price for %s from response: %s", token_address, price_data)
        return self._fetch_and_cache_dexscreener_price(cache_key, token_address, chain)

    def _cached_price(self, cache_key: tuple[str, str]) -> float:
        cached = self._price_cache.get(cache_key)
        if cached is None:
            return 0.0
        price, cached_at = cached
        if time.monotonic() - cached_at > self._price_cache_ttl_seconds:
            self._price_cache.pop(cache_key, None)
            return 0.0
        return price

    def _store_price(self, cache_key: tuple[str, str], price: float) -> None:
        self._price_cache[cache_key] = (price, time.monotonic())

    def _fetch_and_cache_dexscreener_price(
        self,
        cache_key: tuple[str, str],
        token_address: str,
        chain: str,
    ) -> float:
        price = self._fetch_dexscreener_price(token_address, chain)
        if price > 0:
            self._store_price(cache_key, price)
        return price

    def _fetch_dexscreener_price(self, token_address: str, chain: str) -> float:
        chain_id = _dexscreener_chain_id(chain)
        try:
            pairs = fetch_tokens_payload(chain_id, [token_address])
        except Exception as e:
            logger.warning("DEX Screener price fallback failed for %s: %s", token_address, e)
            return 0.0

        for pair in pairs:
            if not isinstance(pair, dict):
                continue
            base_token = pair.get("baseToken")
            if isinstance(base_token, dict):
                address = base_token.get("address")
                if isinstance(address, str) and address.lower() != token_address.lower():
                    continue
            try:
                price = float(pair.get("priceUsd"))
            except (TypeError, ValueError):
                continue
            if price > 0:
                return price
        return 0.0

    # ------------------------------------------------------------------
    # Portfolio updates
    # ------------------------------------------------------------------

    def update_portfolio_prices(
        self,
        portfolio: PortfolioTracker,
        chain: str = "sol",
    ) -> list[dict[str, Any]]:
        """Update prices for all open positions in the portfolio.

        Args:
            portfolio: The portfolio tracker to update.
            chain: Blockchain identifier (default ``"sol"``).

        Returns:
            List of update log entries, each containing ``token_address``,
            ``price``, and ``timestamp``.
        """
        update_log: list[dict[str, Any]] = []
        positions = portfolio.list_positions()

        for position in positions:
            price = self.fetch_token_price(position.token_address, chain)
            portfolio.update_price(position.token_address, price)

            log_entry = {
                "token_address": position.token_address,
                "price": price,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            update_log.append(log_entry)

        return update_log

    def get_position_value(
        self,
        token_address: str,
        portfolio: PortfolioTracker,
    ) -> float:
        """Return the current USD value of a specific position.

        Args:
            token_address: Token contract / mint address.
            portfolio: The portfolio tracker.

        Returns:
            Position value = current_price × quantity.
        """
        position = portfolio.get_position(token_address)
        if position is None:
            return 0.0
        return position.current_price_sol * position.quantity


def _dexscreener_chain_id(chain: str) -> str:
    return {
        "sol": "solana",
        "bsc": "bsc",
        "base": "base",
        "eth": "ethereum",
    }.get(chain, chain)


def _is_rate_limit_error(error: BirdeyeApiError) -> bool:
    return error.http_status == 429 or "too many requests" in error.message.lower()
