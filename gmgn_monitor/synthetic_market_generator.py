from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any

from .backtest_strategies import BuySignal

__all__ = [
    "SyntheticMarketGenerator",
]


class SyntheticMarketGenerator:
    """Generate realistic synthetic market data for backtesting.

    Creates correlated token price movements and wallet buy signals
    that reflect real market dynamics (pumps, dumps, consolidations).
    """

    def __init__(self, seed: int = 42) -> None:
        self._rng = random.Random(seed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_market_scenario(
        self,
        scenario: str = "mixed",
        token_count: int = 5,
        hours: int = 168,
    ) -> dict[str, list[dict]]:
        """Generate price data for multiple tokens in a market scenario.

        Supported scenarios: ``"bull"``, ``"bear"``, ``"mixed"``,
        ``"pump_and_dump"``, ``"volatile"``.
        """
        if scenario == "bull":
            return self._generate_bull_scenario(token_count, hours)
        if scenario == "bear":
            return self._generate_bear_scenario(token_count, hours)
        if scenario == "pump_and_dump":
            return self._generate_pump_and_dump(token_count, hours)
        if scenario == "volatile":
            return self._generate_volatile_scenario(token_count, hours)
        return self._generate_mixed_scenario(token_count, hours)

    def generate_wallet_signals(
        self,
        wallets: list[str],
        token_data: dict[str, list[dict]],
        scenario: str = "mixed",
    ) -> list[BuySignal]:
        """Generate realistic buy signals from wallets.

        Smart wallets buy early in uptrends, average wallets buy late.
        """
        signals: list[BuySignal] = []
        if not wallets or not token_data:
            return signals

        # First half are "smart", second half are "average"
        smart_wallets = wallets[: len(wallets) // 2]
        average_wallets = wallets[len(wallets) // 2 :]

        for token, series in token_data.items():
            if not series:
                continue

            first_price = series[0].get("close", series[0].get("price", 100.0))
            last_price = series[-1].get("close", series[-1].get("price", 100.0))
            is_uptrend = last_price > first_price

            # Smart wallets buy early (first 20 % of the series)
            for wallet in smart_wallets:
                if self._rng.random() < 0.3:
                    idx = self._rng.randint(0, max(1, len(series) // 5))
                    entry = series[idx]
                    price = entry.get("close", entry.get("price", 100.0))
                    ts = entry.get("timestamp", entry.get("time", ""))
                    confidence = 0.7 + self._rng.random() * 0.3
                    signals.append(
                        BuySignal(
                            wallet_address=wallet,
                            token_address=token,
                            timestamp=ts,
                            price_usd=price,
                            amount_sol=0.5 + self._rng.random() * 0.5,
                            confidence=round(confidence, 4),
                        )
                    )

            # Average wallets buy later (mid to end)
            for wallet in average_wallets:
                if self._rng.random() < 0.2:
                    if is_uptrend:
                        start_idx = len(series) // 3
                        end_idx = len(series) * 2 // 3
                    else:
                        start_idx = len(series) // 2
                        end_idx = len(series) - 1
                    idx = self._rng.randint(
                        start_idx, max(start_idx + 1, end_idx)
                    )
                    entry = series[idx]
                    price = entry.get("close", entry.get("price", 100.0))
                    ts = entry.get("timestamp", entry.get("time", ""))
                    confidence = 0.3 + self._rng.random() * 0.4
                    signals.append(
                        BuySignal(
                            wallet_address=wallet,
                            token_address=token,
                            timestamp=ts,
                            price_usd=price,
                            amount_sol=0.3 + self._rng.random() * 0.4,
                            confidence=round(confidence, 4),
                        )
                    )

        return signals

    # ------------------------------------------------------------------
    # Scenario generators
    # ------------------------------------------------------------------

    def _generate_bull_scenario(
        self, token_count: int, hours: int
    ) -> dict[str, list[dict]]:
        """All tokens trending up."""
        result: dict[str, list[dict]] = {}
        for i in range(token_count):
            token = f"BullToken{i}{'1' * 30}"
            trend = 0.08 + self._rng.uniform(0.0, 0.02)
            volatility = 0.02
            result[token] = self._generate_single_token_ohlcv(
                token, 100.0, trend, volatility, hours
            )
        return result

    def _generate_bear_scenario(
        self, token_count: int, hours: int
    ) -> dict[str, list[dict]]:
        """All tokens trending down."""
        result: dict[str, list[dict]] = {}
        for i in range(token_count):
            token = f"BearToken{i}{'2' * 30}"
            trend = -0.08 - self._rng.uniform(0.0, 0.02)
            volatility = 0.02
            result[token] = self._generate_single_token_ohlcv(
                token, 100.0, trend, volatility, hours
            )
        return result

    def _generate_pump_and_dump(
        self, token_count: int, hours: int
    ) -> dict[str, list[dict]]:
        """Rapid rise then crash."""
        result: dict[str, list[dict]] = {}
        pump_hours = max(1, hours // 3)
        dump_hours = max(1, hours - pump_hours)

        for i in range(token_count):
            token = f"PumpDumpToken{i}{'3' * 30}"
            pump_data = self._generate_single_token_ohlcv(
                token, 100.0, 0.10, 0.03, pump_hours
            )
            peak_price = (
                pump_data[-1].get("close", 100.0) if pump_data else 100.0
            )

            # Dump phase starts one hour after pump ends
            last_ts = pump_data[-1].get("timestamp", "") if pump_data else ""
            start_dt = datetime(2025, 6, 1, 0, 0, 0)
            if last_ts:
                try:
                    start_dt = datetime.fromisoformat(
                        last_ts.replace("Z", "+00:00")
                    ) + timedelta(hours=1)
                except ValueError:
                    pass

            dump_data = self._generate_single_token_ohlcv(
                f"{token}_dump",
                peak_price,
                -0.08,
                0.03,
                dump_hours,
                start_time=start_dt,
            )
            result[token] = pump_data + dump_data

        return result

    def _generate_mixed_scenario(
        self, token_count: int, hours: int
    ) -> dict[str, list[dict]]:
        """2 bull, 2 bear, 1 sideways."""
        result: dict[str, list[dict]] = {}
        scenarios = ["bull", "bull", "bear", "bear", "sideways"]
        for i in range(min(token_count, len(scenarios))):
            token = f"MixedToken{i}{'4' * 30}"
            if scenarios[i] == "bull":
                trend = 0.08
                volatility = 0.02
            elif scenarios[i] == "bear":
                trend = -0.08
                volatility = 0.02
            else:
                trend = 0.0
                volatility = 0.02
            result[token] = self._generate_single_token_ohlcv(
                token, 100.0, trend, volatility, hours
            )
        return result

    def _generate_volatile_scenario(
        self, token_count: int, hours: int
    ) -> dict[str, list[dict]]:
        """High volatility, no clear trend."""
        result: dict[str, list[dict]] = {}
        for i in range(token_count):
            token = f"VolatileToken{i}{'5' * 30}"
            result[token] = self._generate_single_token_ohlcv(
                token, 100.0, 0.0, 0.30, hours
            )
        return result

    def _generate_single_token_ohlcv(
        self,
        token_address: str,
        base_price: float,
        trend_bias: float,
        volatility: float,
        hours: int,
        start_time: datetime | None = None,
    ) -> list[dict]:
        """Generate OHLCV for a single token."""
        rng = random.Random(
            hash(token_address) % 10000 + self._rng.randint(0, 1000)
        )
        drift_per_step = trend_bias / 10.0
        candles: list[dict] = []
        current_price = base_price

        start = start_time or datetime(2025, 6, 1, 0, 0, 0)

        for i in range(hours):
            timestamp = (start + timedelta(hours=i)).isoformat()
            random_normal = rng.gauss(0, 1)
            close_price = current_price * (
                1 + drift_per_step + volatility * random_normal
            )
            close_price = max(close_price, 0.01)

            open_price = current_price
            high_price = max(open_price, close_price) * (1 + rng.uniform(0, 0.02))
            low_price = min(open_price, close_price) * (1 - rng.uniform(0, 0.02))
            low_price = max(low_price, 0.001)

            base_volume = 1000.0
            volume = base_volume * (1 + rng.uniform(-0.3, 0.5))
            volume = max(volume, 1.0)

            candles.append(
                {
                    "timestamp": timestamp,
                    "open": round(open_price, 4),
                    "high": round(high_price, 4),
                    "low": round(low_price, 4),
                    "close": round(close_price, 4),
                    "volume": round(volume, 2),
                }
            )

            current_price = close_price

        return candles
