from __future__ import annotations

"""Signal Engine — Convert wallet activity data into structured buy signals.

The :class:`SignalEngine` is the bridge between raw wallet activity (trades,
swaps, transfers) and the structured :class:`~backtest_strategies.BuySignal`
objects that backtest strategies consume.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from .backtest_strategies import BuySignal


__all__ = [
    "SignalEngine",
    "SignalStats",
]


@dataclass(frozen=True)
class SignalStats:
    """Aggregated statistics about extracted signals."""

    total_signals: int = 0
    buy_signals: int = 0
    sell_signals: int = 0
    unique_tokens: int = 0
    unique_wallets: int = 0
    avg_confidence: float = 0.0
    consensus_signals: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_signals": self.total_signals,
            "buy_signals": self.buy_signals,
            "sell_signals": self.sell_signals,
            "unique_tokens": self.unique_tokens,
            "unique_wallets": self.unique_wallets,
            "avg_confidence": round(self.avg_confidence, 4),
            "consensus_signals": self.consensus_signals,
        }


class SignalEngine:
    """Convert wallet activity data into structured buy signals for backtesting.

    The engine expects a mapping of wallet addresses to lists of activity
    entries.  Each entry is a flat dict with the following keys (all
    optional — missing values get sensible defaults):

    * ``token_address`` — str
    * ``action`` — str: ``buy``, ``purchase``, ``swap_in`` (buy side) or
      ``sell``, ``swap_out`` (sell side)
    * ``price`` — float: price in USD at the time of the action
    * ``amount`` — float: amount in SOL
    * ``timestamp`` — str: ISO-8601 timestamp
    * ``confidence`` — float: 0-1 (optional, default 0.7)

    Usage::

        engine = SignalEngine(wallet_scores={"Wallet1": 85.0, "Wallet2": 72.0})
        signals = engine.extract_buy_signals(wallet_activity)
        filtered = engine.filter_signals_by_wallet_score(signals, min_score=60.0)
        consensus = engine.find_consensus_signals(filtered, min_wallets=3)
    """

    def __init__(self, wallet_scores: dict[str, float]) -> None:
        """wallet_scores: {wallet_address: total_score}"""
        self.wallet_scores = wallet_scores

    # ------------------------------------------------------------------
    # Core extraction
    # ------------------------------------------------------------------

    def extract_buy_signals(
        self,
        wallet_activity: dict[str, list[dict]],
    ) -> list[BuySignal]:
        """Extract buy signals from wallet activity data.

        wallet_activity: {wallet_address: [activity_entry, ...]}
        activity_entry: {token_address, action, price, amount, timestamp}

        Returns a list of :class:`BuySignal` objects for all buy-side actions.
        """
        signals: list[BuySignal] = []
        for wallet_address, activities in wallet_activity.items():
            score = self.wallet_scores.get(wallet_address, 50.0)
            for entry in activities:
                if not isinstance(entry, dict):
                    continue
                action = str(entry.get("action", "")).lower()
                if not action:
                    action = str(entry.get("direction", "")).lower()
                if action not in ("buy", "purchase", "swap_in"):
                    continue
                try:
                    price = float(entry.get("price", 0.0))
                    amount = float(entry.get("amount", 0.0))
                    if amount <= 0:
                        amount = float(entry.get("amount_sol", 0.0))
                    ts = str(entry.get("timestamp", ""))
                    token = str(entry.get("token_address", ""))
                    if price <= 0 or amount <= 0 or not token or not ts:
                        continue
                    confidence = float(entry.get("confidence", 0.7))
                    # Scale confidence by wallet score (0-100 → 0-1)
                    wallet_conf = min(1.0, max(0.0, score / 100.0))
                    blended_conf = confidence * 0.5 + wallet_conf * 0.5
                    signals.append(
                        BuySignal(
                            wallet_address=wallet_address,
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

    def extract_all_signals(
        self,
        wallet_activity: dict[str, list[dict]],
    ) -> tuple[list[BuySignal], list[BuySignal]]:
        """Extract both buy and sell signals from wallet activity.

        Returns (buy_signals, sell_signals).
        """
        buy_signals: list[BuySignal] = []
        sell_signals: list[BuySignal] = []
        for wallet_address, activities in wallet_activity.items():
            score = self.wallet_scores.get(wallet_address, 50.0)
            for entry in activities:
                if not isinstance(entry, dict):
                    continue
                action = str(entry.get("action", "")).lower()
                if not action:
                    action = str(entry.get("direction", "")).lower()
                try:
                    price = float(entry.get("price", 0.0))
                    amount = float(entry.get("amount", 0.0))
                    if amount <= 0:
                        amount = float(entry.get("amount_sol", 0.0))
                    ts = str(entry.get("timestamp", ""))
                    token = str(entry.get("token_address", ""))
                    if price <= 0 or amount <= 0 or not token or not ts:
                        continue
                    confidence = float(entry.get("confidence", 0.7))
                    wallet_conf = min(1.0, max(0.0, score / 100.0))
                    blended_conf = confidence * 0.5 + wallet_conf * 0.5
                    signal = BuySignal(
                        wallet_address=wallet_address,
                        token_address=token,
                        timestamp=ts,
                        price_usd=price,
                        amount_sol=amount,
                        confidence=round(blended_conf, 4),
                    )
                    if action in ("buy", "purchase", "swap_in"):
                        buy_signals.append(signal)
                    elif action in ("sell", "swap_out"):
                        sell_signals.append(signal)
                except (ValueError, TypeError):
                    continue
        return buy_signals, sell_signals

    # ------------------------------------------------------------------
    # Filtering & grouping
    # ------------------------------------------------------------------

    def filter_signals_by_wallet_score(
        self,
        signals: list[BuySignal],
        min_score: float = 60.0,
    ) -> list[BuySignal]:
        """Keep only signals whose originating wallet has a score >= min_score.

        The wallet score is looked up from the ``wallet_scores`` dict that was
        passed to the constructor.  If a wallet is not in the dict, the
        signal is discarded (conservative default).
        """
        return [
            s for s in signals
            if self.wallet_scores.get(s.wallet_address, 0) >= min_score
        ]

    def group_signals_by_token(
        self,
        signals: list[BuySignal],
    ) -> dict[str, list[BuySignal]]:
        """Group signals by token_address."""
        grouped: dict[str, list[BuySignal]] = defaultdict(list)
        for signal in signals:
            grouped[signal.token_address].append(signal)
        return dict(grouped)

    def group_signals_by_wallet(
        self,
        signals: list[BuySignal],
    ) -> dict[str, list[BuySignal]]:
        """Group signals by wallet_address."""
        grouped: dict[str, list[BuySignal]] = defaultdict(list)
        for signal in signals:
            grouped[signal.wallet_address].append(signal)
        return dict(grouped)

    # ------------------------------------------------------------------
    # Consensus detection
    # ------------------------------------------------------------------

    def find_consensus_signals(
        self,
        signals: list[BuySignal],
        min_wallets: int = 3,
        time_window_hours: int = 6,
    ) -> list[BuySignal]:
        """Find tokens that multiple wallets bought within a time window.

        A consensus signal is emitted for the first time-window cluster that
        contains at least *min_wallets* distinct wallet addresses buying the
        same token.  The signal's confidence is the maximum of the individual
        confidences, and the price is the average of the cluster.
        """
        grouped = self.group_signals_by_token(signals)
        consensus: list[BuySignal] = []

        for token, token_signals in grouped.items():
            # Sort chronologically
            token_signals.sort(key=lambda s: s.timestamp)

            # Sliding window to find the first cluster with enough wallets
            for i, anchor in enumerate(token_signals):
                try:
                    anchor_dt = datetime.fromisoformat(
                        anchor.timestamp.replace("Z", "+00:00")
                    )
                except ValueError:
                    continue

                window_signals: list[BuySignal] = [anchor]
                wallet_set: set[str] = {anchor.wallet_address}

                for other in token_signals[i + 1 :]:
                    try:
                        other_dt = datetime.fromisoformat(
                            other.timestamp.replace("Z", "+00:00")
                        )
                    except ValueError:
                        continue
                    if (other_dt - anchor_dt) <= timedelta(hours=time_window_hours):
                        window_signals.append(other)
                        wallet_set.add(other.wallet_address)

                if len(wallet_set) >= min_wallets:
                    avg_price = sum(s.price_usd for s in window_signals) / len(
                        window_signals
                    )
                    max_conf = max(s.confidence for s in window_signals)
                    total_amount = sum(s.amount_sol for s in window_signals)
                    consensus.append(
                        BuySignal(
                            wallet_address="consensus",
                            token_address=token,
                            timestamp=anchor.timestamp,
                            price_usd=round(avg_price, 6),
                            amount_sol=round(total_amount, 6),
                            confidence=round(max_conf, 4),
                        )
                    )
                    break  # One consensus signal per token

        return consensus

    # ------------------------------------------------------------------
    # Confidence recalculation
    # ------------------------------------------------------------------

    def calculate_signal_confidence(self, signals: list[BuySignal]) -> list[BuySignal]:
        """Recalculate confidence based on wallet scores and consensus.

        For each signal, the new confidence is::

            base = wallet_score / 100.0  (from the constructor dict)
            boost = 0.1 * log2(1 + distinct_wallets_buying_same_token)
            new_conf = min(1.0, base + boost)

        Returns a new list of signals with updated confidence values.
        """
        from math import log2

        grouped = self.group_signals_by_token(signals)
        token_wallet_counts: dict[str, int] = {
            token: len({s.wallet_address for s in sigs})
            for token, sigs in grouped.items()
        }

        recalculated: list[BuySignal] = []
        for signal in signals:
            base = self.wallet_scores.get(signal.wallet_address, 50.0) / 100.0
            wallet_count = token_wallet_counts.get(signal.token_address, 1)
            boost = 0.1 * log2(1 + wallet_count)
            new_conf = min(1.0, base + boost)
            recalculated.append(
                BuySignal(
                    wallet_address=signal.wallet_address,
                    token_address=signal.token_address,
                    timestamp=signal.timestamp,
                    price_usd=signal.price_usd,
                    amount_sol=signal.amount_sol,
                    confidence=round(new_conf, 4),
                )
            )
        return recalculated

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_stats(self, signals: list[BuySignal]) -> SignalStats:
        """Compute summary statistics for a list of signals."""
        if not signals:
            return SignalStats()
        buy_count = sum(1 for s in signals if s.amount_sol > 0)
        sell_count = len(signals) - buy_count
        unique_tokens = len({s.token_address for s in signals})
        unique_wallets = len({s.wallet_address for s in signals})
        avg_conf = sum(s.confidence for s in signals) / len(signals)
        return SignalStats(
            total_signals=len(signals),
            buy_signals=buy_count,
            sell_signals=sell_count,
            unique_tokens=unique_tokens,
            unique_wallets=unique_wallets,
            avg_confidence=avg_conf,
        )

    def get_consensus_stats(
        self,
        signals: list[BuySignal],
        min_wallets: int = 3,
        time_window_hours: int = 6,
    ) -> SignalStats:
        """Compute stats for consensus signals only."""
        consensus = self.find_consensus_signals(signals, min_wallets, time_window_hours)
        stats = self.get_stats(consensus)
        return SignalStats(
            total_signals=stats.total_signals,
            buy_signals=stats.buy_signals,
            sell_signals=stats.sell_signals,
            unique_tokens=stats.unique_tokens,
            unique_wallets=stats.unique_wallets,
            avg_confidence=stats.avg_confidence,
            consensus_signals=stats.total_signals,
        )
