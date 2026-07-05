from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any

from .backtest_strategies import BuySignal
from .birdeye_client import BirdeyeClient, BirdeyeApiError
from .helius_client import HeliusClient, HeliusApiError
from .ohlcv_cache import OhlcvCache

__all__ = [
    "BacktestDataLoader",
]


class BacktestDataLoader:
    """Load historical price data for backtesting.

    Priority:
    1. Real data from Birdeye API (if API key available)
    2. Helius RPC historical data (if available — currently not implemented
       because the Helius client does not expose an OHLCV endpoint)
    3. Realistic synthetic data with configurable trend / volatility
    """

    def __init__(
        self,
        birdeye_api_key: str | None = None,
        helius_api_key: str | None = None,
    ) -> None:
        self._birdeye_with_key = BirdeyeClient(api_key=birdeye_api_key) if birdeye_api_key else None
        self._birdeye = self._birdeye_with_key  # backward compatibility for existing tests
        self._birdeye_public = BirdeyeClient()  # Always available, no key needed
        self._helius = HeliusClient(api_key=helius_api_key) if helius_api_key else None
        self._helius_api_key = helius_api_key  # backward compatibility for existing tests
        self._cache = OhlcvCache()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_ohlcv(
        self,
        token_address: str,
        chain: str = "sol",
        timeframe: str = "1H",
        limit: int = 168,
    ) -> list[dict]:
        """Load OHLCV candles.

        Returns ``[{timestamp, open, high, low, close, volume}, ...]``.
        Uses a fallback chain:
        1. Check local cache
        2. Birdeye public (no API key)
        3. Birdeye with key
        4. Helius price history
        5. Synthetic data
        """
        # 1. Check cache first
        cached = self._cache.get(token_address, chain, timeframe, limit)
        if cached is not None:
            return cached

        # 2. Try Birdeye public (no key needed)
        if self._birdeye_public:
            try:
                data = self._birdeye_public.get_token_history_ohlcv(
                    token_address,
                    timeframe=timeframe,
                    limit=limit,
                    chain=chain,
                )
                if data:
                    self._cache.set(token_address, chain, timeframe, limit, data)
                    return data
            except (BirdeyeApiError, Exception):
                pass

        # 3. Try Birdeye with key
        if self._birdeye_with_key:
            try:
                data = self._birdeye_with_key.get_token_history_ohlcv(
                    token_address,
                    timeframe=timeframe,
                    limit=limit,
                    chain=chain,
                )
                if data:
                    self._cache.set(token_address, chain, timeframe, limit, data)
                    return data
            except (BirdeyeApiError, Exception):
                pass

        # 4. Try Helius
        if self._helius:
            try:
                data = self._helius.get_token_price_history(
                    token_address,
                    limit=limit,
                )
                if data:
                    normalized = self._normalize_helius_price_history(data)
                    self._cache.set(token_address, chain, timeframe, limit, normalized)
                    return normalized
            except (HeliusApiError, Exception):
                pass

        # 5. Fallback to synthetic
        synthetic = self.generate_realistic_synthetic_ohlcv(
            token_address, hours=limit
        )
        self._cache.set(token_address, chain, timeframe, limit, synthetic)
        return synthetic

    def load_ohlcv_for_wallet_signals(
        self,
        signals: list[BuySignal],
        chain: str = "sol",
        timeframe: str = "1H",
        pre_window: int = 24,
        post_window: int = 168,
    ) -> dict[str, list[dict]]:
        """Load OHLCV for all tokens mentioned in *signals*.

        Returns ``{token_address: [candle, ...]}``.
        """
        if not signals:
            return {}

        # Determine time range from signals
        timestamps = [s.timestamp for s in signals]
        try:
            dt_list = [datetime.fromisoformat(t.replace("Z", "+00:00")) for t in timestamps]
            first = min(dt_list)
            last = max(dt_list)
            start = first - timedelta(hours=pre_window)
            end = last + timedelta(hours=post_window)
        except ValueError:
            start = datetime.min
            end = datetime.max

        tokens = {s.token_address for s in signals}
        result: dict[str, list[dict]] = {}

        for token in tokens:
            if self._birdeye_with_key:
                try:
                    data = self._birdeye_with_key.get_token_history_ohlcv(
                        token, timeframe=timeframe, limit=168, chain=chain
                    )
                    if data:
                        filtered = self._filter_by_time_range(data, start, end)
                        if filtered:
                            result[token] = filtered
                            continue
                except BirdeyeApiError:
                    pass

            # Fallback to synthetic
            total_hours = pre_window + post_window
            result[token] = self.generate_realistic_synthetic_ohlcv(
                token, base_price=100.0, hours=total_hours
            )

        return result

    def generate_realistic_synthetic_ohlcv(
        self,
        token_address: str,
        base_price: float = 100.0,
        trend_bias: float = 0.0,
        volatility: float = 0.15,
        hours: int = 168,
    ) -> list[dict]:
        """Generate realistic synthetic OHLCV with trend and volatility.

        Uses a discrete geometric Brownian motion with drift:
        ``close[t+1] = close[t] * (1 + drift + volatility * random_normal)``.
        """
        rng = random.Random(hash(token_address) % 10000)
        drift_per_step = trend_bias / 10.0
        candles: list[dict] = []
        current_price = base_price

        now = datetime.now()

        for i in range(hours):
            timestamp = (now - timedelta(hours=hours - i)).isoformat()
            random_normal = rng.gauss(0, 1)
            close_price = current_price * (1 + drift_per_step + volatility * random_normal)
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

    def get_price_at_timestamp(
        self, ohlcv: list[dict], timestamp: str
    ) -> float | None:
        """Get the closest price at a given timestamp.

        Looks for the candle whose ``timestamp`` is nearest to the
        requested *timestamp* and returns its ``close`` price.
        """
        if not ohlcv:
            return None

        try:
            target = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return None

        closest_diff = float("inf")
        closest_price = None

        for candle in ohlcv:
            ts = candle.get("timestamp", "")
            if not ts:
                ts = candle.get("time", "")
            if not ts:
                continue

            try:
                candle_dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            except ValueError:
                continue

            diff = abs((candle_dt - target).total_seconds())
            if diff < closest_diff:
                closest_diff = diff
                closest_price = candle.get("close") or candle.get("price")

        return closest_price

    def get_price_series(self, token_address: str, chain: str = "sol", hours: int = 168) -> list[dict]:
        """Get a simple price series for backtest_engine.

        Returns ``[{timestamp: str, price: float}, ...]`` sorted by timestamp.
        """
        ohlcv = self.load_ohlcv(
            token_address, chain=chain, timeframe="1H", limit=hours
        )
        return self.convert_ohlcv_to_price_series(ohlcv)

    def convert_ohlcv_to_price_series(self, ohlcv: list[dict]) -> list[dict]:
        """Convert OHLCV to simple price series for ``backtest_engine``.

        Returns ``[{timestamp, price}, ...]`` using the close price.
        """
        return [
            {
                "timestamp": c.get("timestamp") or c.get("time", ""),
                "price": c.get("close", c.get("price", 0.0)),
            }
            for c in ohlcv
            if c.get("timestamp") or c.get("time")
        ]

    def _normalize_helius_price_history(self, raw: list[dict]) -> list[dict]:
        """Normalize Helius price history to standard OHLCV format.

        Helius returns ``[{timestamp, price}, ...]`` or similar.
        We infer OHLCV from the price points by creating hourly candles.
        """
        if not raw:
            return []

        from datetime import datetime, timezone

        items = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            timestamp = item.get("timestamp", item.get("time", ""))
            price = item.get("price", item.get("value", 0.0))
            if isinstance(price, str):
                try:
                    price = float(price)
                except ValueError:
                    price = 0.0
            if timestamp and price is not None:
                items.append((timestamp, float(price)))

        if not items:
            return []

        # Sort by timestamp
        items.sort(key=lambda x: x[0])

        # Group into hourly candles (simplified)
        candles: list[dict] = []
        bucket: list[float] = []
        bucket_ts = None
        for ts, price in items:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                continue
            hour_key = dt.replace(minute=0, second=0, microsecond=0)
            if bucket_ts is None or hour_key != bucket_ts:
                if bucket:
                    candles.append({
                        "timestamp": bucket_ts.isoformat() if bucket_ts else ts,
                        "open": bucket[0],
                        "high": max(bucket),
                        "low": min(bucket),
                        "close": bucket[-1],
                        "volume": 0.0,
                    })
                bucket = [price]
                bucket_ts = hour_key
            else:
                bucket.append(price)

        if bucket:
            candles.append({
                "timestamp": bucket_ts.isoformat() if bucket_ts else ts,
                "open": bucket[0],
                "high": max(bucket),
                "low": min(bucket),
                "close": bucket[-1],
                "volume": 0.0,
            })

        return candles

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _filter_by_time_range(
        self,
        data: list[dict],
        start: datetime,
        end: datetime,
    ) -> list[dict]:
        """Keep candles that fall within [*start*, *end*]."""
        filtered: list[dict] = []
        for candle in data:
            ts = candle.get("timestamp", "")
            if not ts:
                ts = candle.get("time", "")
            if not ts:
                filtered.append(candle)
                continue
            try:
                candle_dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                if start <= candle_dt <= end:
                    filtered.append(candle)
            except ValueError:
                filtered.append(candle)
        return filtered
