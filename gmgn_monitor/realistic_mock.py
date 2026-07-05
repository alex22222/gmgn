from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any


__all__ = [
    "RealisticMockGenerator",
    "PROFILE_DEFAULT_DISTRIBUTION",
    "PROFILE_RANGES",
]


# ---------------------------------------------------------------------------
# Profile distribution defaults
# ---------------------------------------------------------------------------

PROFILE_DEFAULT_DISTRIBUTION: dict[str, float] = {
    "smart": 0.20,
    "average": 0.35,
    "weak": 0.25,
    "bot": 0.15,
    "elite": 0.05,
}


# ---------------------------------------------------------------------------
# Profile parameter ranges (min, max, typical)
# ---------------------------------------------------------------------------

PROFILE_RANGES: dict[str, dict[str, tuple[float, float]]] = {
    "smart": {
        "win_rate": (60.0, 95.0),
        "total_trades": (50.0, 300.0),
        "avg_profit_usd": (500.0, 5000.0),
        "avg_holding_hours": (12.0, 72.0),
        "total_profit_usd": (5000.0, 50000.0),
        "portfolio_value_usd": (10000.0, 50000.0),
        "stablecoin_balance_usd": (2000.0, 10000.0),
        "trades_7d": (30.0, 100.0),
        "trades_30d": (150.0, 400.0),
        "max_drawdown": (15.0, 40.0),
    },
    "average": {
        "win_rate": (45.0, 65.0),
        "total_trades": (20.0, 150.0),
        "avg_profit_usd": (-500.0, 500.0),
        "avg_holding_hours": (2.0, 24.0),
        "total_profit_usd": (-5000.0, 5000.0),
        "portfolio_value_usd": (2000.0, 15000.0),
        "stablecoin_balance_usd": (500.0, 3000.0),
        "trades_7d": (10.0, 60.0),
        "trades_30d": (50.0, 200.0),
        "max_drawdown": (25.0, 55.0),
    },
    "weak": {
        "win_rate": (30.0, 50.0),
        "total_trades": (10.0, 100.0),
        "avg_profit_usd": (-2000.0, -100.0),
        "avg_holding_hours": (0.5, 6.0),
        "total_profit_usd": (-20000.0, -1000.0),
        "portfolio_value_usd": (1000.0, 8000.0),
        "stablecoin_balance_usd": (200.0, 1500.0),
        "trades_7d": (5.0, 40.0),
        "trades_30d": (20.0, 120.0),
        "max_drawdown": (40.0, 80.0),
    },
    "bot": {
        "win_rate": (48.0, 52.0),
        "total_trades": (200.0, 800.0),
        "avg_profit_usd": (-50.0, 50.0),
        "avg_holding_hours": (0.1, 0.8),
        "total_profit_usd": (-500.0, 500.0),
        "portfolio_value_usd": (5000.0, 20000.0),
        "stablecoin_balance_usd": (1000.0, 5000.0),
        "trades_7d": (300.0, 600.0),
        "trades_30d": (800.0, 2000.0),
        "max_drawdown": (5.0, 20.0),
        "self_transfer_ratio": (60.0, 95.0),
    },
    "elite": {
        "win_rate": (85.0, 99.0),
        "total_trades": (200.0, 600.0),
        "avg_profit_usd": (5000.0, 50000.0),
        "avg_holding_hours": (24.0, 120.0),
        "total_profit_usd": (50000.0, 500000.0),
        "portfolio_value_usd": (50000.0, 500000.0),
        "stablecoin_balance_usd": (10000.0, 50000.0),
        "trades_7d": (50.0, 150.0),
        "trades_30d": (300.0, 600.0),
        "max_drawdown": (10.0, 30.0),
    },
}


# ---------------------------------------------------------------------------
# RealisticMockGenerator
# ---------------------------------------------------------------------------

class RealisticMockGenerator:
    """Generate realistic mock wallet data that mirrors actual GMGN distributions.

    Supports five distinct profiles:

    * **smart** — Smart money wallets with high win rates and consistent profits.
    * **average** — Typical retail traders with mixed results.
    * **weak** — Loss-making traders with poor discipline.
    * **bot** — Ultra-high-frequency bots with near-zero profit and tiny holds.
    * **elite** — Whale wallets with exceptional performance and large capital.

    Usage::

        gen = RealisticMockGenerator(seed=42)
        wallet = gen.generate_wallet(profile="smart")
        batch = gen.generate_batch(count=100)
        stats = gen.generate_wallet_stats("wallet_address_123")
    """

    def __init__(self, seed: int = 42) -> None:
        self._rng = random.Random(seed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_wallet(self, profile: str = "random") -> dict[str, Any]:
        """Generate one wallet in the flat format used by ``WalletFetcher``.

        *profile* can be ``"smart"``, ``"average"``, ``"weak"``, ``"bot"``,
        ``"elite"``, or ``"random"`` (randomly picks a profile).
        """
        if profile == "random":
            profile = self._pick_random_profile()

        ranges = PROFILE_RANGES.get(profile, PROFILE_RANGES["average"])
        addr = self._random_wallet_address()
        chain = "solana"

        win_rate = self._in_range(ranges["win_rate"])
        total_trades = self._int_in_range(ranges["total_trades"])
        avg_profit = self._in_range(ranges["avg_profit_usd"])
        avg_holding = self._in_range(ranges["avg_holding_hours"])
        total_profit = self._in_range(ranges["total_profit_usd"])
        portfolio_value = self._in_range(ranges["portfolio_value_usd"])
        stablecoin_balance = self._in_range(ranges["stablecoin_balance_usd"])
        trades_7d = self._int_in_range(ranges["trades_7d"])
        trades_30d = self._int_in_range(ranges["trades_30d"])
        max_drawdown = self._in_range(ranges["max_drawdown"])

        # Correlate total_profit with avg_profit and total_trades for realism
        if profile not in ("bot",):
            expected_total = avg_profit * total_trades
            total_profit = (total_profit + expected_total) / 2.0
            total_lo, total_hi = ranges["total_profit_usd"]
            total_profit = max(total_lo, min(total_hi, total_profit))
            # Clamp to the declared range to keep tests deterministic
            total_lo, total_hi = ranges["total_profit_usd"]
            total_profit = max(total_lo, min(total_hi, total_profit))

        winning_trades_30d = int(trades_30d * win_rate / 100.0)
        avg_investment = max(50.0, portfolio_value / max(total_trades / 10.0, 1.0))

        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        first_seen = self._random_first_seen()

        return {
            "wallet_address": addr,
            "chain": chain,
            "first_seen_at": first_seen,
            "last_active_at": now,
            "source": "gmgn_realistic_mock",
            "fetched_at": now,
            "total_trades_7d": trades_7d,
            "total_trades_30d": trades_30d,
            "winning_trades_30d": winning_trades_30d,
            "win_rate_30d": round(win_rate, 2),
            "avg_investment_usd": round(avg_investment, 2),
            "avg_profit_usd": round(avg_profit, 2),
            "total_profit_usd": round(total_profit, 2),
            "avg_holding_duration_hours": round(avg_holding, 2),
            "stablecoin_balance_usd": round(stablecoin_balance, 2),
            "portfolio_balance_usd": round(portfolio_value, 2),
            "max_drawdown": round(max_drawdown, 2),
            "self_transfer_ratio_percent": round(
                self._in_range((60.0, 95.0)) if profile == "bot" else self._in_range((0.0, 15.0)), 2
            ),
        }

    def generate_batch(
        self,
        count: int,
        distribution: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        """Generate a batch of wallets with a realistic profile distribution.

        Args:
            count: Number of wallets to generate.
            distribution: Mapping of ``profile -> weight`` (must sum to 1.0).
                Defaults to :data:`PROFILE_DEFAULT_DISTRIBUTION`.

        Returns:
            A list of flat wallet dicts.
        """
        if count <= 0:
            return []

        dist = distribution or PROFILE_DEFAULT_DISTRIBUTION
        profiles = list(dist.keys())
        weights = [dist.get(p, 0.0) for p in profiles]

        batch: list[dict[str, Any]] = []
        for _ in range(count):
            profile = self._rng.choices(profiles, weights=weights, k=1)[0]
            batch.append(self.generate_wallet(profile=profile))
        return batch

    def generate_wallet_stats(
        self,
        wallet_address: str,
        chain: str = "sol",
    ) -> dict[str, Any]:
        """Generate GMGN ``wallet_stats`` format for a single wallet.

        Returns a flat dict compatible with
        :func:`~gmgn_monitor.gmgn_data_mapper.map_wallet_stats_to_features`.
        """
        profile = self._pick_random_profile()
        ranges = PROFILE_RANGES.get(profile, PROFILE_RANGES["average"])

        win_rate = self._in_range(ranges["win_rate"])
        total_trades = self._int_in_range(ranges["total_trades"])
        avg_profit = self._in_range(ranges["avg_profit_usd"])
        avg_holding = self._in_range(ranges["avg_holding_hours"])
        total_profit = self._in_range(ranges["total_profit_usd"])
        portfolio_value = self._in_range(ranges["portfolio_value_usd"])
        balance_usd = self._in_range(ranges["stablecoin_balance_usd"])
        trades_7d = self._int_in_range(ranges["trades_7d"])
        trades_30d = self._int_in_range(ranges["trades_30d"])
        max_drawdown = self._in_range(ranges["max_drawdown"])

        if profile not in ("bot",):
            expected_total = avg_profit * total_trades
            total_profit = (total_profit + expected_total) / 2.0
            total_lo, total_hi = ranges["total_profit_usd"]
            total_profit = max(total_lo, min(total_hi, total_profit))

        realized_profit = total_profit * 0.75
        unrealized_profit = total_profit - realized_profit
        pnl_30d = total_profit * 0.6 / portfolio_value if portfolio_value > 0 else 0.0
        pnl_7d = pnl_30d / 4.0

        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        first_seen = self._random_first_seen()
        days_since_last = self._rng.randint(0, 3)
        last_active = self._offset_days(now, -days_since_last)

        return {
            "wallet_address": wallet_address,
            "chain": chain,
            "total_profit": round(total_profit, 2),
            "realized_profit": round(realized_profit, 2),
            "unrealized_profit": round(unrealized_profit, 2),
            "win_rate": round(win_rate, 2),
            "total_trades": total_trades,
            "trades_7d": trades_7d,
            "trades_30d": trades_30d,
            "avg_holding_time": round(avg_holding, 2),
            "pnl_7d": round(pnl_7d, 4),
            "pnl_30d": round(pnl_30d, 4),
            "max_drawdown": round(max_drawdown, 2),
            "portfolio_value": round(portfolio_value, 2),
            "balance_usd": round(balance_usd, 2),
            "first_seen_at": first_seen,
            "last_active_at": last_active,
            "days_since_last_trade": float(days_since_last),
            "mev_attacker": profile == "bot" and self._rng.random() < 0.3,
            "dev_wallet": False,
            "sniper_detected": profile == "bot" and self._rng.random() < 0.5,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _pick_random_profile(self) -> str:
        """Pick a random profile according to the default distribution."""
        profiles = list(PROFILE_DEFAULT_DISTRIBUTION.keys())
        weights = list(PROFILE_DEFAULT_DISTRIBUTION.values())
        return self._rng.choices(profiles, weights=weights, k=1)[0]

    def _in_range(self, range_tuple: tuple[float, float]) -> float:
        """Return a random float uniformly distributed within *range_tuple*."""
        lo, hi = range_tuple
        return self._rng.uniform(lo, hi)

    def _int_in_range(self, range_tuple: tuple[float, float]) -> int:
        """Return a random int uniformly distributed within *range_tuple*."""
        lo, hi = range_tuple
        return int(self._rng.uniform(lo, hi))

    def _random_wallet_address(self) -> str:
        """Generate a random-looking Solana-style base58 address."""
        chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
        body = "".join(self._rng.choices(chars, k=32))
        return f"GMGN{body}"

    def _random_first_seen(self) -> str:
        """Return a random ISO timestamp between 30 and 730 days ago."""
        days_ago = self._rng.randint(30, 730)
        dt = datetime.now(timezone.utc)
        # Simple offset: subtract days
        from datetime import timedelta
        dt = dt - timedelta(days=days_ago)
        return dt.isoformat().replace("+00:00", "Z")

    def _offset_days(self, iso_str: str, days: int) -> str:
        """Offset an ISO timestamp by *days* (can be negative)."""
        from datetime import timedelta
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        dt = dt + timedelta(days=days)
        return dt.isoformat().replace("+00:00", "Z")
