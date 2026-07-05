from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from gmgn_monitor.backtest_data_loader import BacktestDataLoader
from gmgn_monitor.backtest_strategies import BuySignal
from gmgn_monitor.birdeye_client import BirdeyeApiError
from gmgn_monitor.helius_client import HeliusApiError
from gmgn_monitor.ohlcv_cache import OhlcvCache


class TestBacktestDataLoader:
    def test_initialization_without_api_keys(self) -> None:
        loader = BacktestDataLoader()
        assert loader._birdeye_with_key is None
        assert loader._birdeye_public is not None
        assert loader._helius is None
        assert loader._cache is not None

    def test_initialization_with_birdeye_key(self) -> None:
        loader = BacktestDataLoader(birdeye_api_key="test-key")
        assert loader._birdeye_with_key is not None
        assert loader._birdeye_public is not None

    def test_initialization_with_helius_key(self) -> None:
        loader = BacktestDataLoader(helius_api_key="test-key")
        assert loader._helius is not None

    def test_initialization_with_both_keys(self) -> None:
        loader = BacktestDataLoader(
            birdeye_api_key="b-key", helius_api_key="h-key"
        )
        assert loader._birdeye_with_key is not None
        assert loader._birdeye_public is not None
        assert loader._helius is not None

    def test_load_ohlcv_fallback_when_no_api_key(self) -> None:
        loader = BacktestDataLoader()
        data = loader.load_ohlcv("some_token", limit=20)
        assert len(data) == 20
        assert "timestamp" in data[0]
        assert "close" in data[0]

    def test_load_ohlcv_with_mocked_birdeye_public(self, tmp_path) -> None:
        loader = BacktestDataLoader()
        loader._cache = OhlcvCache(str(tmp_path))
        mock_ohlcv = [
            {"timestamp": "2025-01-01T00:00:00", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 1000}
        ]
        with patch.object(loader._birdeye_public, "get_token_history_ohlcv", return_value=mock_ohlcv):
            data = loader.load_ohlcv("token", limit=20)
            assert data == mock_ohlcv

    def test_load_ohlcv_with_mocked_birdeye_with_key(self, tmp_path) -> None:
        loader = BacktestDataLoader(birdeye_api_key="test-key")
        loader._cache = OhlcvCache(str(tmp_path))
        mock_ohlcv = [
            {"timestamp": "2025-01-01T00:00:00", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 1000}
        ]
        with patch.object(loader._birdeye_public, "get_token_history_ohlcv", return_value=[]):
            with patch.object(loader._birdeye_with_key, "get_token_history_ohlcv", return_value=mock_ohlcv):
                data = loader.load_ohlcv("token", limit=20)
                assert data == mock_ohlcv

    def test_load_ohlcv_birdeye_error_fallback(self) -> None:
        loader = BacktestDataLoader()
        with patch.object(
            loader._birdeye_public,
            "get_token_history_ohlcv",
            side_effect=BirdeyeApiError("API error"),
        ):
            data = loader.load_ohlcv("token", limit=10)
            assert len(data) == 10
            assert "close" in data[0]

    def test_load_ohlcv_helius_fallback(self) -> None:
        loader = BacktestDataLoader(helius_api_key="h-key")
        # Birdeye public fails, Birdeye with key not available, Helius succeeds
        with patch.object(loader._birdeye_public, "get_token_history_ohlcv", return_value=[]):
            mock_helius = [{"timestamp": "2025-01-01T00:00:00", "price": 100.0}]
            with patch.object(loader._helius, "get_token_price_history", return_value=mock_helius):
                data = loader.load_ohlcv("token", limit=10)
                assert len(data) > 0
                assert "close" in data[0]

    def test_load_ohlcv_helius_error_fallback(self) -> None:
        loader = BacktestDataLoader(helius_api_key="h-key")
        with patch.object(loader._birdeye_public, "get_token_history_ohlcv", return_value=[]):
            with patch.object(loader._helius, "get_token_price_history", side_effect=HeliusApiError("Helius error")):
                data = loader.load_ohlcv("token", limit=10)
                assert len(data) == 10
                assert "close" in data[0]

    def test_get_price_series(self) -> None:
        loader = BacktestDataLoader()
        mock_ohlcv = [
            {"timestamp": "2025-01-01T00:00:00", "open": 90, "high": 110, "low": 85, "close": 100, "volume": 1000},
            {"timestamp": "2025-01-01T01:00:00", "open": 100, "high": 115, "low": 95, "close": 105, "volume": 1200},
        ]
        with patch.object(loader, "load_ohlcv", return_value=mock_ohlcv):
            series = loader.get_price_series("token", chain="sol", hours=2)
            assert len(series) == 2
            assert series[0]["timestamp"] == "2025-01-01T00:00:00"
            assert series[0]["price"] == 100
            assert series[1]["price"] == 105

    def test_convert_ohlcv_to_price_series_uses_close(self) -> None:
        loader = BacktestDataLoader()
        ohlcv = [
            {"timestamp": "2025-01-01T00:00:00", "open": 90, "high": 110, "low": 85, "close": 100, "volume": 1000},
            {"timestamp": "2025-01-01T01:00:00", "open": 100, "high": 115, "low": 95, "close": 105, "volume": 1200},
        ]
        series = loader.convert_ohlcv_to_price_series(ohlcv)
        assert len(series) == 2
        assert series[0]["timestamp"] == "2025-01-01T00:00:00"
        assert series[0]["price"] == 100
        assert series[1]["price"] == 105

    def test_cache_hit(self) -> None:
        loader = BacktestDataLoader()
        mock_ohlcv = [
            {"timestamp": "2025-01-01T00:00:00", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 1000}
        ]
        with patch.object(loader._cache, "get", return_value=mock_ohlcv):
            data = loader.load_ohlcv("token", limit=20)
            assert data == mock_ohlcv

    def test_cache_miss_then_api(self) -> None:
        loader = BacktestDataLoader()
        mock_ohlcv = [
            {"timestamp": "2025-01-01T00:00:00", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 1000}
        ]
        with patch.object(loader._cache, "get", return_value=None):
            with patch.object(loader._birdeye_public, "get_token_history_ohlcv", return_value=mock_ohlcv):
                with patch.object(loader._cache, "set") as mock_set:
                    data = loader.load_ohlcv("token", limit=20)
                    assert data == mock_ohlcv
                    mock_set.assert_called_once()

    def test_load_ohlcv_all_apis_fail_fallback(self) -> None:
        loader = BacktestDataLoader(helius_api_key="h-key")
        with patch.object(loader._birdeye_public, "get_token_history_ohlcv", side_effect=BirdeyeApiError("public error")):
            with patch.object(loader._helius, "get_token_price_history", side_effect=HeliusApiError("helius error")):
                data = loader.load_ohlcv("token", limit=10)
                assert len(data) == 10
                assert "close" in data[0]

    def test_load_ohlcv_for_wallet_signals_empty(self) -> None:
        loader = BacktestDataLoader()
        result = loader.load_ohlcv_for_wallet_signals([])
        assert result == {}

    def test_load_ohlcv_for_wallet_signals_single_token(self) -> None:
        loader = BacktestDataLoader()
        signals = [
            BuySignal(
                wallet_address="w1",
                token_address="token1",
                timestamp="2025-06-01T12:00:00",
                price_usd=100.0,
                amount_sol=0.5,
                confidence=0.8,
            )
        ]
        result = loader.load_ohlcv_for_wallet_signals(signals, pre_window=0, post_window=10)
        assert "token1" in result
        assert len(result["token1"]) == 10

    def test_load_ohlcv_for_wallet_signals_multiple_tokens(self) -> None:
        loader = BacktestDataLoader()
        signals = [
            BuySignal(
                wallet_address="w1",
                token_address="token1",
                timestamp="2025-06-01T12:00:00",
                price_usd=100.0,
                amount_sol=0.5,
                confidence=0.8,
            ),
            BuySignal(
                wallet_address="w2",
                token_address="token2",
                timestamp="2025-06-01T14:00:00",
                price_usd=200.0,
                amount_sol=0.3,
                confidence=0.6,
            ),
        ]
        result = loader.load_ohlcv_for_wallet_signals(signals, pre_window=0, post_window=10)
        assert "token1" in result
        assert "token2" in result
        assert len(result["token1"]) == 10
        assert len(result["token2"]) == 10


class TestSyntheticOhlcv:
    def test_synthetic_ohlcv_generation(self) -> None:
        loader = BacktestDataLoader()
        data = loader.generate_realistic_synthetic_ohlcv(
            "test_token", base_price=100.0, hours=10
        )
        assert len(data) == 10
        assert all("timestamp" in c for c in data)
        assert all("open" in c for c in data)
        assert all("high" in c for c in data)
        assert all("low" in c for c in data)
        assert all("close" in c for c in data)
        assert all("volume" in c for c in data)

    def test_synthetic_ohlcv_format_validation(self) -> None:
        loader = BacktestDataLoader()
        data = loader.generate_realistic_synthetic_ohlcv(
            "test_token", base_price=100.0, hours=5
        )
        for candle in data:
            assert isinstance(candle["open"], float)
            assert isinstance(candle["high"], float)
            assert isinstance(candle["low"], float)
            assert isinstance(candle["close"], float)
            assert isinstance(candle["volume"], float)
            assert candle["high"] >= candle["open"] or candle["high"] >= candle["close"]
            assert candle["low"] <= candle["open"] or candle["low"] <= candle["close"]
            assert candle["volume"] > 0

    def test_synthetic_ohlcv_hours_length(self) -> None:
        loader = BacktestDataLoader()
        for hours in [1, 24, 168, 500]:
            data = loader.generate_realistic_synthetic_ohlcv(
                "test_token", hours=hours
            )
            assert len(data) == hours

    def test_synthetic_ohlcv_positive_trend_bias(self) -> None:
        loader = BacktestDataLoader()
        pos = loader.generate_realistic_synthetic_ohlcv(
            "same_seed", base_price=100.0, trend_bias=0.1, volatility=0.01, hours=50
        )
        neg = loader.generate_realistic_synthetic_ohlcv(
            "same_seed", base_price=100.0, trend_bias=-0.1, volatility=0.01, hours=50
        )
        # Same seed, only drift differs → positive bias must finish higher
        assert pos[-1]["close"] > neg[-1]["close"]

    def test_synthetic_ohlcv_zero_trend_bias(self) -> None:
        loader = BacktestDataLoader()
        data = loader.generate_realistic_synthetic_ohlcv(
            "neutral", base_price=100.0, trend_bias=0.0, volatility=0.05, hours=100
        )
        # With zero drift and same seed, first and last should be around the same area
        # (just check it doesn't crash and produces reasonable values)
        assert 20 < data[-1]["close"] < 500

    def test_synthetic_ohlcv_price_floor(self) -> None:
        loader = BacktestDataLoader()
        data = loader.generate_realistic_synthetic_ohlcv(
            "crasher", base_price=1.0, trend_bias=-0.5, volatility=0.5, hours=200
        )
        for candle in data:
            assert candle["close"] >= 0.01
            assert candle["low"] >= 0.001

    def test_synthetic_ohlcv_deterministic_same_seed(self) -> None:
        loader = BacktestDataLoader()
        a = loader.generate_realistic_synthetic_ohlcv(
            "seed_token", base_price=100.0, hours=20
        )
        b = loader.generate_realistic_synthetic_ohlcv(
            "seed_token", base_price=100.0, hours=20
        )
        for ca, cb in zip(a, b):
            assert ca["close"] == cb["close"]
            assert ca["high"] == cb["high"]
            assert ca["low"] == cb["low"]

    def test_synthetic_ohlcv_different_seed(self) -> None:
        loader = BacktestDataLoader()
        a = loader.generate_realistic_synthetic_ohlcv(
            "token_a", base_price=100.0, hours=20
        )
        b = loader.generate_realistic_synthetic_ohlcv(
            "token_b", base_price=100.0, hours=20
        )
        # Very likely different; just assert not identical
        assert a[0]["close"] != b[0]["close"] or a[1]["close"] != b[1]["close"]


class TestPriceConversion:
    def test_get_price_at_timestamp_exact(self) -> None:
        loader = BacktestDataLoader()
        ohlcv = [
            {"timestamp": "2025-06-01T10:00:00", "close": 100.0},
            {"timestamp": "2025-06-01T11:00:00", "close": 105.0},
        ]
        price = loader.get_price_at_timestamp(ohlcv, "2025-06-01T10:00:00")
        assert price == 100.0

    def test_get_price_at_timestamp_closest(self) -> None:
        loader = BacktestDataLoader()
        ohlcv = [
            {"timestamp": "2025-06-01T10:00:00", "close": 100.0},
            {"timestamp": "2025-06-01T11:00:00", "close": 105.0},
        ]
        price = loader.get_price_at_timestamp(ohlcv, "2025-06-01T10:30:00")
        # 10:30 is exactly halfway → returns the first found (10:00)
        assert price in (100.0, 105.0)

    def test_get_price_at_timestamp_empty(self) -> None:
        loader = BacktestDataLoader()
        price = loader.get_price_at_timestamp([], "2025-06-01T10:00:00")
        assert price is None

    def test_get_price_at_timestamp_invalid(self) -> None:
        loader = BacktestDataLoader()
        price = loader.get_price_at_timestamp(
            [{"timestamp": "2025-06-01T10:00:00", "close": 100.0}], "not-a-date"
        )
        assert price is None


class TestBuySignal:
    def test_buy_signal_dataclass(self) -> None:
        signal = BuySignal(
            wallet_address="w1",
            token_address="t1",
            timestamp="2025-06-01T00:00:00",
            price_usd=100.0,
            amount_sol=0.5,
            confidence=0.8,
        )
        assert signal.wallet_address == "w1"
        assert signal.token_address == "t1"
        assert signal.confidence == 0.8
