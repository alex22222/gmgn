"""Signal preprocessing pipeline.

Filters incoming :class:`~trade_signal.TradeSignal` objects before they reach
the CSS engine.  Supports deduplication, blacklisting, quality-gating,
wallet-score gating, and expiry checks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from gmgn_monitor.trade_signal import TradeSignal


__all__ = [
    "PreprocessStats",
    "PreprocessResult",
    "SignalPreprocessor",
]


@dataclass
class PreprocessStats:
    """Counters for a single batch or cumulative processing run."""

    total_processed: int = 0
    accepted: int = 0
    rejected: int = 0
    deduplicated: int = 0
    blacklisted: int = 0
    below_quality: int = 0
    below_wallet_score: int = 0
    expired: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_processed": self.total_processed,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "deduplicated": self.deduplicated,
            "blacklisted": self.blacklisted,
            "below_quality": self.below_quality,
            "below_wallet_score": self.below_wallet_score,
            "expired": self.expired,
        }


@dataclass(frozen=True)
class PreprocessResult:
    """Output of a single ``process()`` call."""

    accepted: list[TradeSignal]
    rejected: list[TradeSignal]
    stats: PreprocessStats
    details: dict[str, Any] = field(default_factory=dict)


class SignalPreprocessor:
    """Multi-stage signal preprocessor.

    Filters are applied in the following order:

    1. **expiry_filter** – drop signals where ``is_expired()`` is ``True``.
    2. **blacklist_filter** – drop signals whose token or wallet is blacklisted.
    3. **quality_gate** – drop signals with ``quality_score < min_confidence``.
    4. **wallet_score_gate** – drop signals whose originating wallet score
       (looked up from the *wallet_scores* dict) is below *min_wallet_score*.
    5. **deduplicate** – within *dedup_window_seconds*, keep only the highest
       ``quality_score`` signal per ``(wallet_address, target_token)`` pair.

    Usage::

        preprocessor = SignalPreprocessor(
            blacklist_tokens={"BAD_TOKEN"},
            min_confidence=60,
            min_wallet_score=55.0,
        )
        result = preprocessor.process(
            signals=incoming_signals,
            wallet_scores={"Wallet1": 85.0, "Wallet2": 42.0},
        )
        # result.accepted  -> signals that passed all filters
        # result.rejected  -> signals that were filtered out
        # result.stats     -> per-batch counters
    """

    def __init__(
        self,
        blacklist_tokens: set[str] | None = None,
        blacklist_wallets: set[str] | None = None,
        min_confidence: int = 50,
        min_wallet_score: float = 50.0,
        dedup_window_seconds: float = 300.0,
    ) -> None:
        self.blacklist_tokens: set[str] = set(blacklist_tokens or [])
        self.blacklist_wallets: set[str] = set(blacklist_wallets or [])
        self.min_confidence = min_confidence
        self.min_wallet_score = min_wallet_score
        self.dedup_window_seconds = dedup_window_seconds

        # Streaming deduplication state: (wallet, token) -> last_seen datetime
        self._last_seen: dict[tuple[str, str], datetime] = {}
        # Track the quality score of the last accepted signal for dedup comparison
        self._last_quality: dict[tuple[str, str], int] = {}

        self._cumulative_stats = PreprocessStats()

    @property
    def stats(self) -> PreprocessStats:
        """Cumulative statistics across all ``process()`` calls."""
        return self._cumulative_stats

    def add_blacklist_token(self, token: str) -> None:
        """Add a token to the blacklist."""
        self.blacklist_tokens.add(token)

    def add_blacklist_wallet(self, wallet: str) -> None:
        """Add a wallet address to the blacklist."""
        self.blacklist_wallets.add(wallet)

    def process(
        self,
        signals: list[TradeSignal],
        wallet_scores: dict[str, float] | None = None,
    ) -> PreprocessResult:
        """Run the full preprocessing pipeline on a batch of signals.

        Args:
            signals: List of incoming trade signals.
            wallet_scores: Optional mapping ``{wallet_address: score}`` used by
                the wallet-score gate. Wallets not in the dict receive a default
                score of ``0.0`` (conservative behaviour).

        Returns:
            A :class:`PreprocessResult` with *accepted*, *rejected*, and
            per-batch *stats*.
        """
        wallet_scores = wallet_scores or {}
        accepted: list[TradeSignal] = []
        rejected: list[TradeSignal] = []
        batch_stats = PreprocessStats()

        for signal in signals:
            batch_stats.total_processed += 1

            # 1. Expiry filter
            if signal.is_expired():
                rejected.append(signal)
                batch_stats.expired += 1
                batch_stats.rejected += 1
                continue

            # 2. Blacklist filter
            if (
                signal.target_token in self.blacklist_tokens
                or signal.wallet_address in self.blacklist_wallets
            ):
                rejected.append(signal)
                batch_stats.blacklisted += 1
                batch_stats.rejected += 1
                continue

            # 3. Quality gate
            if signal.quality_score < self.min_confidence:
                rejected.append(signal)
                batch_stats.below_quality += 1
                batch_stats.rejected += 1
                continue

            # 4. Wallet score gate
            ws = wallet_scores.get(signal.wallet_address, 0.0)
            if ws < self.min_wallet_score:
                rejected.append(signal)
                batch_stats.below_wallet_score += 1
                batch_stats.rejected += 1
                continue

            # 5. Deduplicate
            key = (signal.wallet_address, signal.target_token)
            now = signal.received_at

            if key in self._last_seen:
                last_time = self._last_seen[key]
                delta = (now - last_time).total_seconds()
                if delta <= self.dedup_window_seconds:
                    # Same (wallet, token) within the dedup window
                    if signal.quality_score <= self._last_quality.get(key, 0):
                        # New signal has lower or equal quality – reject as dup
                        rejected.append(signal)
                        batch_stats.deduplicated += 1
                        batch_stats.rejected += 1
                        continue
                    # New signal has higher quality – replace the previously
                    # accepted signal in the current batch if it is present.
                    batch_stats.deduplicated += 1
                    prev_quality = self._last_quality.get(key, 0)
                    for idx, acc in enumerate(accepted):
                        if (
                            acc.wallet_address == signal.wallet_address
                            and acc.target_token == signal.target_token
                            and acc.quality_score == prev_quality
                        ):
                            accepted.pop(idx)
                            batch_stats.accepted -= 1
                            break

            self._last_seen[key] = now
            self._last_quality[key] = signal.quality_score
            accepted.append(signal)
            batch_stats.accepted += 1

        # Update cumulative stats
        self._cumulative_stats = PreprocessStats(
            total_processed=self._cumulative_stats.total_processed
            + batch_stats.total_processed,
            accepted=self._cumulative_stats.accepted + batch_stats.accepted,
            rejected=self._cumulative_stats.rejected + batch_stats.rejected,
            deduplicated=self._cumulative_stats.deduplicated + batch_stats.deduplicated,
            blacklisted=self._cumulative_stats.blacklisted + batch_stats.blacklisted,
            below_quality=self._cumulative_stats.below_quality + batch_stats.below_quality,
            below_wallet_score=self._cumulative_stats.below_wallet_score
            + batch_stats.below_wallet_score,
            expired=self._cumulative_stats.expired + batch_stats.expired,
        )

        return PreprocessResult(
            accepted=accepted,
            rejected=rejected,
            stats=batch_stats,
            details={
                "dedup_window_seconds": self.dedup_window_seconds,
                "min_confidence": self.min_confidence,
                "min_wallet_score": self.min_wallet_score,
                "blacklist_tokens_count": len(self.blacklist_tokens),
                "blacklist_wallets_count": len(self.blacklist_wallets),
            },
        )

    def reset_dedup_state(self) -> None:
        """Clear the internal deduplication tracking.

        Useful when switching to a completely new signal stream or after a
        long pause where stale dedup windows are no longer relevant.
        """
        self._last_seen.clear()
        self._last_quality.clear()
