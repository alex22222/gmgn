from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from gmgn_monitor.ohlcv_cache import OhlcvCache, DEFAULT_CACHE_DIR


class TestOhlcvCache:
    """Tests for the OhlcvCache class."""

    def test_initialization_default_dir(self) -> None:
        cache = OhlcvCache()
        assert cache._cache_dir == DEFAULT_CACHE_DIR
        assert cache._cache_dir.exists()

    def test_initialization_custom_dir(self, tmp_path: Path) -> None:
        custom_dir = tmp_path / "custom_cache"
        cache = OhlcvCache(str(custom_dir))
        assert cache._cache_dir == custom_dir
        assert custom_dir.exists()

    def test_cache_get_miss(self, tmp_path: Path) -> None:
        cache = OhlcvCache(str(tmp_path))
        result = cache.get("token123", "sol", "1H", 168)
        assert result is None

    def test_cache_set_and_get(self, tmp_path: Path) -> None:
        cache = OhlcvCache(str(tmp_path))
        data = [
            {"timestamp": "2025-01-01T00:00:00", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 1000}
        ]
        cache.set("token123", "sol", "1H", 168, data)
        result = cache.get("token123", "sol", "1H", 168)
        assert result is not None
        assert len(result) == 1
        assert result[0]["close"] == 1.5

    def test_cache_is_expired(self, tmp_path: Path) -> None:
        cache = OhlcvCache(str(tmp_path))
        data = [
            {"timestamp": "2025-01-01T00:00:00", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 1000}
        ]
        cache.set("token123", "sol", "1H", 168, data)
        # Should not be expired immediately
        assert not cache.is_expired("token123", "sol", "1H", 168, max_age_hours=1)

    def test_cache_expiration(self, tmp_path: Path) -> None:
        cache = OhlcvCache(str(tmp_path))
        data = [
            {"timestamp": "2025-01-01T00:00:00", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 1000}
        ]
        cache.set("token123", "sol", "1H", 168, data)
        # Simulate age by modifying mtime
        path = cache._cache_path("token123", "sol", "1H", 168)
        old_time = time.time() - 7200  # 2 hours ago
        import os
        os.utime(path, (old_time, old_time))
        assert cache.is_expired("token123", "sol", "1H", 168, max_age_hours=1)
        assert cache.get("token123", "sol", "1H", 168) is None

    def test_cache_clear_all(self, tmp_path: Path) -> None:
        cache = OhlcvCache(str(tmp_path))
        data = [
            {"timestamp": "2025-01-01T00:00:00", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 1000}
        ]
        cache.set("token1", "sol", "1H", 168, data)
        cache.set("token2", "sol", "1H", 168, data)
        cache.clear()
        assert cache.get("token1", "sol", "1H", 168) is None
        assert cache.get("token2", "sol", "1H", 168) is None

    def test_cache_clear_specific_token(self, tmp_path: Path) -> None:
        cache = OhlcvCache(str(tmp_path))
        data = [
            {"timestamp": "2025-01-01T00:00:00", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 1000}
        ]
        cache.set("token1", "sol", "1H", 168, data)
        cache.set("token2", "sol", "1H", 168, data)
        cache.clear("token1")
        assert cache.get("token1", "sol", "1H", 168) is None
        assert cache.get("token2", "sol", "1H", 168) is not None

    def test_cache_path_generation(self, tmp_path: Path) -> None:
        cache = OhlcvCache(str(tmp_path))
        path = cache._cache_path("token123", "sol", "1H", 168)
        assert path.name == "token123_sol_1H_168.json"
        assert path.parent == tmp_path

    def test_cache_with_invalid_json(self, tmp_path: Path) -> None:
        cache = OhlcvCache(str(tmp_path))
        path = cache._cache_path("token123", "sol", "1H", 168)
        path.write_text("not json", encoding="utf-8")
        result = cache.get("token123", "sol", "1H", 168)
        assert result is None

    def test_cache_with_wrong_structure(self, tmp_path: Path) -> None:
        cache = OhlcvCache(str(tmp_path))
        path = cache._cache_path("token123", "sol", "1H", 168)
        path.write_text(json.dumps({"wrong_key": "value"}), encoding="utf-8")
        result = cache.get("token123", "sol", "1H", 168)
        assert result is None

    def test_cache_integration_with_backtest_loader(self, tmp_path: Path) -> None:
        from gmgn_monitor.backtest_data_loader import BacktestDataLoader
        cache = OhlcvCache(str(tmp_path))
        loader = BacktestDataLoader()
        loader._cache = cache
        data = [
            {"timestamp": "2025-01-01T00:00:00", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 1000}
        ]
        with patch.object(loader._birdeye_public, "get_token_history_ohlcv", return_value=data):
            result = loader.load_ohlcv("token123", chain="sol", timeframe="1H", limit=168)
            assert result is not None
            # Second call should hit cache
            result2 = cache.get("token123", "sol", "1H", 168)
            assert result2 is not None
            assert result2 == result
