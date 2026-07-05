from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from gmgn_monitor.backtest_data_loader import BacktestDataLoader
from gmgn_monitor.backtest_engine import BacktestEngine
from gmgn_monitor.backtest_strategies import FixedBuyStrategy
from gmgn_monitor.synthetic_market_generator import SyntheticMarketGenerator


class TestOhlcvIntegration:
    """End-to-end integration tests for the OHLCV pipeline."""

    def test_full_pipeline_backtest_data_loader_to_engine(self) -> None:
        loader = BacktestDataLoader()
        ohlcv = [
            {"timestamp": "2025-01-01T00:00:00", "open": 90, "high": 110, "low": 85, "close": 100, "volume": 1000},
            {"timestamp": "2025-01-01T01:00:00", "open": 100, "high": 115, "low": 95, "close": 105, "volume": 1200},
            {"timestamp": "2025-01-01T02:00:00", "open": 105, "high": 120, "low": 100, "close": 110, "volume": 1500},
        ]
        price_data = {"token1": loader.convert_ohlcv_to_price_series(ohlcv)}
        engine = BacktestEngine()
        strategy = FixedBuyStrategy(fixed_sol_amount=0.5)
        result = engine.run_backtest("wallet1", price_data, strategy.to_config())
        assert result.total_trades > 0

    def test_mocked_birdeve_ohlcv_to_price_series_to_backtest(self) -> None:
        loader = BacktestDataLoader()
        mock_ohlcv = [
            {"timestamp": f"2025-01-01T{t:02d}:00:00", "open": 100, "high": 110, "low": 95, "close": 105, "volume": 1000}
            for t in range(20)
        ]
        with patch.object(loader._birdeye_public, "get_token_history_ohlcv", return_value=mock_ohlcv):
            data = loader.load_ohlcv("token", limit=20)
            price_data = {"token": loader.convert_ohlcv_to_price_series(data)}
            engine = BacktestEngine()
            strategy = FixedBuyStrategy(fixed_sol_amount=0.5)
            result = engine.run_backtest("wallet1", price_data, strategy.to_config())
            assert result.total_trades > 0

    def test_synthetic_ohlcv_to_price_series_to_backtest(self) -> None:
        loader = BacktestDataLoader()
        ohlcv = loader.generate_realistic_synthetic_ohlcv("token", base_price=100.0, hours=20)
        price_data = {"token": loader.convert_ohlcv_to_price_series(ohlcv)}
        engine = BacktestEngine()
        strategy = FixedBuyStrategy(fixed_sol_amount=0.5)
        result = engine.run_backtest("wallet1", price_data, strategy.to_config())
        assert result.total_trades > 0

    def test_bull_market_scenario_positive_expectancy(self) -> None:
        gen = SyntheticMarketGenerator(seed=42)
        market_data = gen.generate_market_scenario("bull", token_count=3, hours=168)
        loader = BacktestDataLoader()
        price_data = {}
        for token, ohlcv in market_data.items():
            price_data[token] = loader.convert_ohlcv_to_price_series(ohlcv)
        engine = BacktestEngine()
        strategy = FixedBuyStrategy(fixed_sol_amount=0.5)
        result = engine.run_backtest("wallet1", price_data, strategy.to_config())
        assert result.total_trades > 0
        # In a bull market, prices generally go up
        assert result.total_return_percent > 0

    def test_bear_market_scenario_negative_expectancy(self) -> None:
        gen = SyntheticMarketGenerator(seed=42)
        market_data = gen.generate_market_scenario("bear", token_count=3, hours=168)
        loader = BacktestDataLoader()
        price_data = {}
        for token, ohlcv in market_data.items():
            price_data[token] = loader.convert_ohlcv_to_price_series(ohlcv)
        engine = BacktestEngine()
        strategy = FixedBuyStrategy(fixed_sol_amount=0.5)
        result = engine.run_backtest("wallet1", price_data, strategy.to_config())
        assert result.total_trades > 0
        # In a bear market, prices generally go down
        assert result.total_return_percent < 0

    def test_mixed_market_scenario(self) -> None:
        gen = SyntheticMarketGenerator(seed=42)
        market_data = gen.generate_market_scenario("mixed", token_count=5, hours=168)
        loader = BacktestDataLoader()
        price_data = {}
        for token, ohlcv in market_data.items():
            price_data[token] = loader.convert_ohlcv_to_price_series(ohlcv)
        engine = BacktestEngine()
        strategy = FixedBuyStrategy(fixed_sol_amount=0.5)
        result = engine.run_backtest("wallet1", price_data, strategy.to_config())
        assert result.total_trades > 0

    def test_cache_hit_no_api_call(self) -> None:
        loader = BacktestDataLoader()
        mock_ohlcv = [
            {"timestamp": "2025-01-01T00:00:00", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 1000}
        ]
        with patch.object(loader._cache, "get", return_value=mock_ohlcv):
            with patch.object(loader._birdeye_public, "get_token_history_ohlcv") as mock_birdeye:
                data = loader.load_ohlcv("token", limit=20)
                assert data == mock_ohlcv
                mock_birdeye.assert_not_called()

    def test_cache_miss_api_call_then_save(self) -> None:
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

    def test_multiple_tokens_backtest(self) -> None:
        loader = BacktestDataLoader()
        tokens = ["token1", "token2", "token3"]
        price_data = {}
        for token in tokens:
            ohlcv = loader.generate_realistic_synthetic_ohlcv(token, base_price=100.0, hours=20)
            price_data[token] = loader.convert_ohlcv_to_price_series(ohlcv)
        engine = BacktestEngine()
        strategy = FixedBuyStrategy(fixed_sol_amount=0.5)
        result = engine.run_backtest("wallet1", price_data, strategy.to_config())
        assert result.total_trades == len(tokens)

    def test_signal_based_backtest_with_real_ohlcv(self) -> None:
        from gmgn_monitor.backtest_strategies import BuySignal
        loader = BacktestDataLoader()
        ohlcv = [
            {"timestamp": f"2025-01-01T{t:02d}:00:00", "open": 100, "high": 110, "low": 95, "close": 105 + t, "volume": 1000}
            for t in range(20)
        ]
        price_data = {"token1": loader.convert_ohlcv_to_price_series(ohlcv)}
        signals = [
            BuySignal(
                wallet_address="w1",
                token_address="token1",
                timestamp="2025-01-01T05:00:00",
                price_usd=110.0,
                amount_sol=0.5,
                confidence=0.8,
            )
        ]
        engine = BacktestEngine()
        strategy = FixedBuyStrategy(fixed_sol_amount=0.5)
        result = engine.run_signal_backtest("wallet1", signals, price_data, strategy.to_config())
        assert result.total_trades > 0

    def test_backtest_with_volatile_market(self) -> None:
        gen = SyntheticMarketGenerator(seed=42)
        market_data = gen.generate_market_scenario("volatile", token_count=3, hours=168)
        loader = BacktestDataLoader()
        price_data = {}
        for token, ohlcv in market_data.items():
            price_data[token] = loader.convert_ohlcv_to_price_series(ohlcv)
        engine = BacktestEngine()
        strategy = FixedBuyStrategy(fixed_sol_amount=0.5)
        result = engine.run_backtest("wallet1", price_data, strategy.to_config())
        assert result.total_trades > 0
        # Volatile market should have some trades with non-zero results
        assert result.total_return_percent != 0

    def test_pump_and_dump_scenario(self) -> None:
        gen = SyntheticMarketGenerator(seed=42)
        market_data = gen.generate_market_scenario("pump_and_dump", token_count=2, hours=168)
        loader = BacktestDataLoader()
        price_data = {}
        for token, ohlcv in market_data.items():
            price_data[token] = loader.convert_ohlcv_to_price_series(ohlcv)
        engine = BacktestEngine()
        strategy = FixedBuyStrategy(fixed_sol_amount=0.5)
        result = engine.run_backtest("wallet1", price_data, strategy.to_config())
        assert result.total_trades > 0
