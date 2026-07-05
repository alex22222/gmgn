from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .backtest_strategies import BuySignal
from .gmgn_api_client import GmgnApiClient
from .gmgn_data_mapper import (
    map_smartmoney_list_to_wallet_addresses,
    map_token_top_traders_to_wallet_addresses,
)
from .trade_signal import TradeSignal

__all__ = [
    "LiveSignalFetcher",
]

logger = logging.getLogger(__name__)


class LiveSignalFetcher:
    """Fetch live trading signals from the GMGN API and convert them into
    structured :class:`BuySignal` and :class:`TradeSignal` objects for the
    DryRun executor.

    Args:
        api_client: An authenticated :class:`GmgnApiClient` instance.
        wallet_scores: Mapping of wallet address -> score (0-100) used to
            weight signal confidence.
    """

    def __init__(
        self,
        api_client: GmgnApiClient,
        wallet_scores: dict[str, float],
    ) -> None:
        self.api_client = api_client
        self.wallet_scores = wallet_scores

    # ------------------------------------------------------------------
    # Smart-money signals
    # ------------------------------------------------------------------

    def fetch_smartmoney_signals(
        self,
        chain: str = "sol",
        limit: int = 50,
    ) -> list[BuySignal]:
        """Fetch top smart-money wallets and their recent buy activity.

        Calls ``GET /v1/user/smartmoney`` to get the top wallet list, then
        for each wallet calls ``GET /v1/user/wallet_activity`` to find
        recent buy actions.  Each buy action is converted into a
        :class:`BuySignal`.

        Args:
            chain: Chain identifier (default ``"sol"``).
            limit: Number of smart-money wallets to fetch.

        Returns:
            A list of :class:`BuySignal` objects.  Returns an empty list on
            any API error (errors are logged).
        """
        signals: list[BuySignal] = []
        try:
            raw = self.api_client.get_smartmoney(chain=chain, limit=limit)
            wallets = map_smartmoney_list_to_wallet_addresses(raw)
            if not isinstance(wallets, list):
                wallets = []
        except Exception as exc:
            logger.error("Failed to fetch smartmoney list: %s", exc)
            return signals

        for wallet in wallets:
            try:
                activity = self.api_client.get_wallet_activity(
                    chain=chain, wallet_address=wallet, limit=20
                )
            except Exception as exc:
                logger.warning("Wallet activity fetch failed for %s: %s", wallet, exc)
                continue

            # Unwrap common response shapes
            entries = activity.get("activities") or activity.get("data") or []
            if isinstance(entries, dict):
                entries = entries.get("activities") or entries.get("data") or []
            if not isinstance(entries, list):
                continue

            score = self.wallet_scores.get(wallet, 50.0)
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                action = str(entry.get("action", "")).lower()
                if action not in ("buy", "purchase", "swap_in"):
                    continue
                try:
                    price = float(entry.get("price", 0.0))
                    amount = float(entry.get("amount", 0.0))
                    if amount <= 0:
                        amount = float(entry.get("amount_sol", 0.0))
                    ts = str(entry.get("timestamp", entry.get("time", "")))
                    token = str(entry.get("token_address", ""))
                    if price <= 0 or amount <= 0 or not token or not ts:
                        continue
                    confidence = float(entry.get("confidence", 0.7))
                    wallet_conf = min(1.0, max(0.0, score / 100.0))
                    blended_conf = confidence * 0.5 + wallet_conf * 0.5
                    signals.append(
                        BuySignal(
                            wallet_address=wallet,
                            token_address=token,
                            timestamp=ts,
                            price_usd=price,
                            amount_sol=amount,
                            confidence=round(blended_conf, 4),
                        )
                    )
                except (ValueError, TypeError):
                    continue

        return signals

    # ------------------------------------------------------------------
    # Trending-token signals
    # ------------------------------------------------------------------

    def fetch_trending_signals(
        self,
        chain: str = "sol",
        interval: str = "1h",
        top_n: int = 10,
    ) -> list[BuySignal]:
        """Fetch trending tokens and create signals from top traders.

        Calls ``GET /v1/market/rank`` (trending swaps) and extracts the top
        *top_n* tokens.  For each token, calls
        ``GET /v1/market/token_top_traders`` to find wallets that recently
        traded it.  Creates a :class:`BuySignal` for each top-trader/token
        pair.

        Args:
            chain: Chain identifier (default ``"sol"``).
            interval: Ranking interval (default ``"1h"``).
            top_n: Number of trending tokens to process.

        Returns:
            A list of :class:`BuySignal` objects.  Returns an empty list on
            any API error (errors are logged).
        """
        signals: list[BuySignal] = []
        try:
            trending = self.api_client.get_trending_swaps(
                chain=chain, interval=interval
            )
            tokens = trending.get("tokens") or trending.get("data") or []
            if isinstance(tokens, dict):
                tokens = tokens.get("tokens") or tokens.get("data") or []
            if not isinstance(tokens, list):
                tokens = []
        except Exception as exc:
            logger.error("Failed to fetch trending swaps: %s", exc)
            return signals

        tokens = tokens[:top_n]

        for token_entry in tokens:
            if not isinstance(token_entry, dict):
                continue
            token_address = str(
                token_entry.get("token_address")
                or token_entry.get("address")
                or ""
            )
            if not token_address:
                continue

            try:
                top_traders = self.api_client.get_token_top_traders(
                    chain=chain, token_address=token_address
                )
            except Exception as exc:
                logger.warning(
                    "Top traders fetch failed for %s: %s", token_address, exc
                )
                continue

            wallets = map_token_top_traders_to_wallet_addresses(top_traders)
            if not isinstance(wallets, list):
                wallets = []

            for wallet in wallets:
                score = self.wallet_scores.get(wallet, 50.0)
                price = float(token_entry.get("price", 0.0))
                if price <= 0:
                    price = 1.0
                amount = 0.5
                ts = str(token_entry.get("timestamp", ""))
                if not ts:
                    ts = datetime.now(timezone.utc).isoformat().replace(
                        "+00:00", "Z"
                    )
                wallet_conf = min(1.0, max(0.0, score / 100.0))
                signals.append(
                    BuySignal(
                        wallet_address=wallet,
                        token_address=token_address,
                        timestamp=ts,
                        price_usd=price,
                        amount_sol=amount,
                        confidence=round(wallet_conf, 4),
                    )
                )

        return signals

    # ------------------------------------------------------------------
    # Conversion helpers
    # ------------------------------------------------------------------

    def to_trade_signals(
        self,
        buy_signals: list[BuySignal],
    ) -> list[TradeSignal]:
        """Convert a list of :class:`BuySignal` objects to :class:`TradeSignal`.

        Uses :meth:`TradeSignal.from_buy_signal` with the wallet-score mapping
        passed to the constructor.

        Args:
            buy_signals: Signals to convert.

        Returns:
            A list of :class:`TradeSignal` objects ready for the
            :class:`DryRunExecutor`.
        """
        trade_signals: list[TradeSignal] = []
        for bs in buy_signals:
            score = self.wallet_scores.get(bs.wallet_address, 0.0)
            trade_signals.append(
                TradeSignal.from_buy_signal(bs, wallet_score=score)
            )
        return trade_signals
