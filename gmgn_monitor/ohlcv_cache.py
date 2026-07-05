from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


__all__ = [
    "OhlcvCache",
]


DEFAULT_CACHE_DIR = Path.home() / ".cache" / "gmgn" / "ohlcv"
DEFAULT_MAX_AGE_HOURS = 1


class OhlcvCache:
    """Local file cache for OHLCV data.

    Cache directory: ``~/.cache/gmgn/ohlcv/``
    File format: ``{token_address}_{chain}_{timeframe}_{limit}.json``
    """

    def __init__(self, cache_dir: str | None = None) -> None:
        self._cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(
        self,
        token_address: str,
        chain: str,
        timeframe: str,
        limit: int,
    ) -> list[dict] | None:
        """Get cached OHLCV data if available and not expired."""
        path = self._cache_path(token_address, chain, timeframe, limit)
        if not path.exists():
            return None

        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

        if not isinstance(data, dict):
            return None

        # Check expiration
        cached_at = data.get("cached_at", 0)
        if cached_at and self.is_expired(token_address, chain, timeframe, limit):
            return None

        ohlcv = data.get("ohlcv")
        if not isinstance(ohlcv, list):
            return None

        return [dict(item) for item in ohlcv if isinstance(item, dict)]

    def set(
        self,
        token_address: str,
        chain: str,
        timeframe: str,
        limit: int,
        data: list[dict],
    ) -> None:
        """Cache OHLCV data."""
        path = self._cache_path(token_address, chain, timeframe, limit)
        payload: dict[str, Any] = {
            "cached_at": time.time(),
            "token_address": token_address,
            "chain": chain,
            "timeframe": timeframe,
            "limit": limit,
            "ohlcv": data,
        }
        try:
            with path.open("w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, default=str)
        except OSError:
            pass

    def is_expired(
        self,
        token_address: str,
        chain: str,
        timeframe: str,
        limit: int,
        max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
    ) -> bool:
        """Check if cached data is older than *max_age_hours*."""
        path = self._cache_path(token_address, chain, timeframe, limit)
        if not path.exists():
            return True

        try:
            mtime = path.stat().st_mtime
        except OSError:
            return True

        age_seconds = time.time() - mtime
        max_age_seconds = max_age_hours * 3600
        return age_seconds > max_age_seconds

    def clear(self, token_address: str | None = None) -> None:
        """Clear cache for a specific token or all tokens."""
        if token_address is None:
            for path in self._cache_dir.iterdir():
                if path.suffix == ".json":
                    try:
                        path.unlink()
                    except OSError:
                        pass
            return

        # Clear all files matching the token address prefix
        prefix = self._sanitize_filename(token_address)
        for path in self._cache_dir.iterdir():
            if path.suffix == ".json" and path.name.startswith(prefix):
                try:
                    path.unlink()
                except OSError:
                    pass

    def _cache_path(
        self,
        token_address: str,
        chain: str,
        timeframe: str,
        limit: int,
    ) -> Path:
        """Build the cache file path for a given token + parameters."""
        safe_token = self._sanitize_filename(token_address)
        filename = f"{safe_token}_{chain}_{timeframe}_{limit}.json"
        return self._cache_dir / filename

    def _sanitize_filename(self, token_address: str) -> str:
        """Sanitize a token address for use as a filename."""
        return token_address.replace("/", "_").replace("\\", "_")
