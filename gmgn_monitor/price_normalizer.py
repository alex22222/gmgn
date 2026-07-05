from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


__all__ = [
    "normalize_birdeye_ohlcv",
    "normalize_helius_price_history",
    "normalize_dexscreener_ohlcv",
    "fill_missing_ohlcv",
    "resample_ohlcv",
]


# ------------------------------------------------------------------
# Birdeye
# ------------------------------------------------------------------

def normalize_birdeye_ohlcv(raw: list[dict] | dict) -> list[dict]:
    """Normalize Birdeye OHLCV response to standard format.

    Standard format: ``[{timestamp, open, high, low, close, volume}, ...]``

    Handles:
    - ``{ "data": { "items": [{unixTime, o, h, l, c, v}] } }`` — nested
    - ``{ "items": [...] }`` — direct
    - ``[{unixTime, o, h, l, c, v}]`` — array with short keys
    - ``[{unixTime, open, high, low, close, volume}]`` — array with full keys
    """
    if raw is None:
        return []

    # Unwrap nested envelopes
    if isinstance(raw, dict):
        raw = _unwrap_birdeye(raw)

    if not isinstance(raw, list):
        return []

    normalized: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        candle = _normalize_single_candle(item)
        if candle is not None:
            normalized.append(candle)

    return normalized


def _unwrap_birdeye(raw: dict) -> list:
    """Extract list from Birdeye response wrappers."""
    if "items" in raw and isinstance(raw["items"], list):
        return raw["items"]
    if "data" in raw and isinstance(raw["data"], dict):
        data = raw["data"]
        if "items" in data and isinstance(data["items"], list):
            return data["items"]
        if isinstance(data, list):
            return data
    if isinstance(raw.get("data"), list):
        return raw["data"]
    return []


def _normalize_single_candle(item: dict) -> dict | None:
    """Normalize a single candle dict to standard keys."""
    ts_raw = item.get("unixTime") or item.get("timestamp") or item.get("time")
    if ts_raw is None:
        return None

    timestamp = _parse_timestamp(ts_raw)
    if timestamp is None:
        return None

    open_price = _extract_price(item, "open", "o")
    high_price = _extract_price(item, "high", "h")
    low_price = _extract_price(item, "low", "l")
    close_price = _extract_price(item, "close", "c")
    volume = _extract_price(item, "volume", "v")

    # If we have at least close or open, build a valid candle
    if close_price is None and open_price is None:
        return None

    return {
        "timestamp": timestamp,
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": close_price,
        "volume": volume,
    }


def _extract_price(item: dict, full_key: str, short_key: str) -> float | None:
    """Extract a numeric price from either full or short key."""
    value = item.get(full_key)
    if value is None:
        value = item.get(short_key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_timestamp(ts_raw: Any) -> str | None:
    """Parse various timestamp formats into ISO 8601 string."""
    if isinstance(ts_raw, str):
        # Already a string — try to parse and re-format
        try:
            dt = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            # If we can't parse it, return as-is if it looks like ISO
            if "T" in ts_raw:
                return ts_raw.replace("+00:00", "Z")
            return None
    if isinstance(ts_raw, int) or isinstance(ts_raw, float):
        # Assume unix timestamp in seconds
        try:
            dt = datetime.fromtimestamp(float(ts_raw), tz=timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except (ValueError, OSError, OverflowError):
            return None
    return None


# ------------------------------------------------------------------
# Helius
# ------------------------------------------------------------------

def normalize_helius_price_history(raw: list[dict] | dict) -> list[dict]:
    """Normalize Helius price history to standard OHLCV format.

    Helius typically returns simple price points:
    ``[{timestamp: "2024-01-01T00:00:00Z", price: 1.23}, ...]``

    We convert each point to a 1-hour OHLCV candle where
    open=high=low=close=price and volume=0 (unknown).
    """
    if raw is None:
        return []

    if isinstance(raw, dict):
        raw = _unwrap_helius(raw)

    if not isinstance(raw, list):
        return []

    normalized: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        ts_raw = item.get("timestamp") or item.get("unixTime") or item.get("time")
        price_raw = item.get("price") or item.get("value")
        if ts_raw is None or price_raw is None:
            continue

        timestamp = _parse_timestamp(ts_raw)
        if timestamp is None:
            continue

        try:
            price = float(price_raw)
        except (TypeError, ValueError):
            continue

        normalized.append({
            "timestamp": timestamp,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": 0.0,
        })

    return normalized


def _unwrap_helius(raw: dict) -> list:
    """Extract list from Helius response wrappers."""
    if "items" in raw and isinstance(raw["items"], list):
        return raw["items"]
    if "data" in raw and isinstance(raw["data"], list):
        return raw["data"]
    if isinstance(raw.get("data"), dict):
        data = raw["data"]
        if "items" in data and isinstance(data["items"], list):
            return data["items"]
    return []


# ------------------------------------------------------------------
# DexScreener
# ------------------------------------------------------------------

def normalize_dexscreener_ohlcv(raw: list[dict] | dict) -> list[dict]:
    """Normalize DexScreener OHLCV response to standard format.

    DexScreener does not expose a dedicated OHLCV endpoint, but if
    price-history data is provided via a third-party integration it
    often follows a similar schema to Birdeye.

    This normalizer delegates to Birdeye logic and adds DexScreener
    specific key mappings (``priceUsd``, ``volumeUsd``).
    """
    if raw is None:
        return []

    if isinstance(raw, dict):
        raw = _unwrap_dexscreener(raw)

    if not isinstance(raw, list):
        return []

    normalized: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        candle = _normalize_dexscreener_candle(item)
        if candle is not None:
            normalized.append(candle)

    return normalized


def _unwrap_dexscreener(raw: dict) -> list:
    """Extract list from DexScreener response wrappers."""
    if "pairs" in raw and isinstance(raw["pairs"], list):
        return raw["pairs"]
    if "items" in raw and isinstance(raw["items"], list):
        return raw["items"]
    if "data" in raw and isinstance(raw["data"], list):
        return raw["data"]
    return []


def _normalize_dexscreener_candle(item: dict) -> dict | None:
    """Normalize a single DexScreener candle."""
    ts_raw = item.get("unixTime") or item.get("timestamp") or item.get("time")
    if ts_raw is None:
        return None

    timestamp = _parse_timestamp(ts_raw)
    if timestamp is None:
        return None

    # DexScreener may use priceUsd / volumeUsd keys
    price = _extract_price(item, "priceUsd", "price")
    if price is None:
        price = _extract_price(item, "close", "c")
    open_price = _extract_price(item, "open", "o") or price
    high_price = _extract_price(item, "high", "h") or price
    low_price = _extract_price(item, "low", "l") or price
    volume = _extract_price(item, "volumeUsd", "volume") or _extract_price(item, "v", "v")

    if price is None:
        return None

    return {
        "timestamp": timestamp,
        "open": open_price,
        "high": high_price,
        "low": low_price,
        "close": price,
        "volume": volume if volume is not None else 0.0,
    }


# ------------------------------------------------------------------
# Missing data filling
# ------------------------------------------------------------------

def fill_missing_ohlcv(ohlcv: list[dict], expected_hours: int) -> list[dict]:
    """Fill missing candles by forward-filling close prices.

    Args:
        ohlcv: Existing OHLCV candles (must be sorted by timestamp).
        expected_hours: Expected number of hourly candles.

    Returns:
        A complete list of hourly candles with no gaps.
    """
    if not ohlcv:
        return []

    # Sort by timestamp
    sorted_candles = sorted(ohlcv, key=lambda c: c.get("timestamp", ""))

    # Parse timestamps into datetime objects
    parsed: list[tuple[datetime, dict]] = []
    for candle in sorted_candles:
        ts_str = candle.get("timestamp")
        if not ts_str:
            continue
        try:
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            parsed.append((dt, candle))
        except ValueError:
            continue

    if not parsed:
        return []

    filled: list[dict] = []
    current_dt = parsed[0][0]
    end_dt = parsed[-1][0]
    candle_idx = 0

    last_close = parsed[0][1].get("close", 0.0)
    if last_close is None:
        last_close = parsed[0][1].get("price", 0.0) or 0.0

    while current_dt <= end_dt and len(filled) < expected_hours:
        # Find matching candle for current hour
        found = False
        while candle_idx < len(parsed):
            cdt, candle = parsed[candle_idx]
            if cdt <= current_dt < (cdt + timedelta(hours=1)):
                filled.append(dict(candle))
                close = candle.get("close")
                if close is not None:
                    last_close = close
                candle_idx += 1
                found = True
                break
            elif cdt < current_dt:
                candle_idx += 1
                continue
            else:
                break

        if not found:
            # Forward-fill
            ts_str = current_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            filled.append({
                "timestamp": ts_str,
                "open": last_close,
                "high": last_close,
                "low": last_close,
                "close": last_close,
                "volume": 0.0,
            })

        current_dt += timedelta(hours=1)

    return filled


# ------------------------------------------------------------------
# Resampling
# ------------------------------------------------------------------

def resample_ohlcv(ohlcv: list[dict], target_timeframe: str) -> list[dict]:
    """Resample OHLCV to a different timeframe.

    Supported target timeframes: ``"1H"``, ``"4H"``, ``"1D"``.
    Assumes input is 1-hour candles.

    Args:
        ohlcv: List of 1-hour OHLCV candles.
        target_timeframe: Target candle interval.

    Returns:
        Resampled OHLCV candles.
    """
    if not ohlcv:
        return []

    # Determine bucket size in hours
    bucket_hours = _timeframe_to_hours(target_timeframe)
    if bucket_hours <= 1:
        return ohlcv

    # Sort by timestamp
    sorted_candles = sorted(ohlcv, key=lambda c: c.get("timestamp", ""))

    buckets: dict[str, list[dict]] = {}
    for candle in sorted_candles:
        ts_str = candle.get("timestamp")
        if not ts_str:
            continue
        try:
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except ValueError:
            continue

        # Bucket key: floor to nearest bucket boundary
        bucket_idx = int(dt.timestamp() // (bucket_hours * 3600))
        bucket_key = str(bucket_idx)
        buckets.setdefault(bucket_key, []).append(candle)

    resampled: list[dict] = []
    for bucket_key in sorted(buckets.keys(), key=int):
        bucket = buckets[bucket_key]
        if not bucket:
            continue

        opens = [c.get("open") for c in bucket if c.get("open") is not None]
        highs = [c.get("high") for c in bucket if c.get("high") is not None]
        lows = [c.get("low") for c in bucket if c.get("low") is not None]
        closes = [c.get("close") for c in bucket if c.get("close") is not None]
        volumes = [c.get("volume") for c in bucket if c.get("volume") is not None]

        if not closes:
            continue

        first_ts = bucket[0].get("timestamp", "")
        resampled.append({
            "timestamp": first_ts,
            "open": opens[0] if opens else closes[0],
            "high": max(highs) if highs else max(closes),
            "low": min(lows) if lows else min(closes),
            "close": closes[-1],
            "volume": sum(volumes) if volumes else 0.0,
        })

    return resampled


def _timeframe_to_hours(timeframe: str) -> int:
    """Convert a timeframe string to hours."""
    mapping = {
        "1m": 1,
        "5m": 1,
        "15m": 1,
        "30m": 1,
        "1H": 1,
        "4H": 4,
        "1D": 24,
    }
    return mapping.get(timeframe, 1)
