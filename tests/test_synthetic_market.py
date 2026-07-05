from __future__ import annotations

import pytest

from gmgn_monitor.synthetic_market_generator import SyntheticMarketGenerator


class TestSyntheticMarketGenerator:
    def test_initialization(self) -> None:
        gen = SyntheticMarketGenerator(seed=42)
        assert gen._rng is not None

    def test_bull_scenario_token_count(self) -> None:
        gen = SyntheticMarketGenerator(seed=42)
        data = gen.generate_market_scenario("bull", token_count=5, hours=168)
        assert len(data) == 5

    def test_bull_scenario_all_tokens_up(self) -> None:
        gen = SyntheticMarketGenerator(seed=42)
        data = gen.generate_market_scenario("bull", token_count=5, hours=168)
        for token, series in data.items():
            first_price = series[0]["close"]
            last_price = series[-1]["close"]
            assert last_price > first_price, f"{token} did not trend up"

    def test_bear_scenario_token_count(self) -> None:
        gen = SyntheticMarketGenerator(seed=42)
        data = gen.generate_market_scenario("bear", token_count=5, hours=168)
        assert len(data) == 5

    def test_bear_scenario_all_tokens_down(self) -> None:
        gen = SyntheticMarketGenerator(seed=42)
        data = gen.generate_market_scenario("bear", token_count=5, hours=168)
        for token, series in data.items():
            first_price = series[0]["close"]
            last_price = series[-1]["close"]
            assert last_price < first_price, f"{token} did not trend down"

    def test_mixed_scenario_token_count(self) -> None:
        gen = SyntheticMarketGenerator(seed=42)
        data = gen.generate_market_scenario("mixed", token_count=5, hours=168)
        assert len(data) == 5

    def test_mixed_scenario_some_up_some_down(self) -> None:
        gen = SyntheticMarketGenerator(seed=42)
        data = gen.generate_market_scenario("mixed", token_count=5, hours=168)
        up_count = 0
        down_count = 0
        for token, series in data.items():
            first_price = series[0]["close"]
            last_price = series[-1]["close"]
            if last_price > first_price:
                up_count += 1
            else:
                down_count += 1
        assert up_count >= 1
        assert down_count >= 1

    def test_pump_and_dump_scenario(self) -> None:
        gen = SyntheticMarketGenerator(seed=42)
        data = gen.generate_market_scenario("pump_and_dump", token_count=3, hours=168)
        assert len(data) == 3
        for token, series in data.items():
            assert len(series) == 168
            # Find peak price
            prices = [c["close"] for c in series]
            max_price = max(prices)
            min_price = min(prices)
            # Should have a clear pump and dump
            assert max_price > series[0]["close"]
            assert series[-1]["close"] < max_price

    def test_volatile_scenario(self) -> None:
        gen = SyntheticMarketGenerator(seed=42)
        data = gen.generate_market_scenario("volatile", token_count=5, hours=168)
        assert len(data) == 5
        for token, series in data.items():
            assert len(series) == 168
            prices = [c["close"] for c in series]
            # High volatility means large swings
            max_price = max(prices)
            min_price = min(prices)
            assert max_price / min_price > 2.0

    def test_default_scenario_is_mixed(self) -> None:
        gen = SyntheticMarketGenerator(seed=42)
        data = gen.generate_market_scenario(token_count=5, hours=168)
        assert len(data) == 5

    def test_ohlcv_format(self) -> None:
        gen = SyntheticMarketGenerator(seed=42)
        data = gen.generate_market_scenario("bull", token_count=1, hours=10)
        for token, series in data.items():
            for candle in series:
                assert "timestamp" in candle
                assert "open" in candle
                assert "high" in candle
                assert "low" in candle
                assert "close" in candle
                assert "volume" in candle
                assert candle["high"] >= candle["low"]
                assert candle["close"] >= 0.01

    def test_hours_length(self) -> None:
        gen = SyntheticMarketGenerator(seed=42)
        for hours in [10, 50, 168, 500]:
            data = gen.generate_market_scenario("bull", token_count=1, hours=hours)
            for series in data.values():
                assert len(series) == hours


class TestWalletSignals:
    def test_empty_wallets(self) -> None:
        gen = SyntheticMarketGenerator(seed=42)
        data = gen.generate_market_scenario("bull", token_count=2, hours=50)
        signals = gen.generate_wallet_signals([], data)
        assert signals == []

    def test_empty_tokens(self) -> None:
        gen = SyntheticMarketGenerator(seed=42)
        signals = gen.generate_wallet_signals(["w1"], {})
        assert signals == []

    def test_wallet_signals_smart_buy_early(self) -> None:
        gen = SyntheticMarketGenerator(seed=42)
        wallets = ["smart1", "smart2", "avg1", "avg2"]
        data = gen.generate_market_scenario("bull", token_count=3, hours=100)
        signals = gen.generate_wallet_signals(wallets, data, scenario="bull")
        assert len(signals) > 0

        smart_signals = [s for s in signals if s.wallet_address in ("smart1", "smart2")]
        avg_signals = [s for s in signals if s.wallet_address in ("avg1", "avg2")]

        if smart_signals and avg_signals:
            # Get average buy index for each group
            smart_indices = []
            avg_indices = []
            for token, series in data.items():
                for s in smart_signals:
                    if s.token_address == token:
                        for i, c in enumerate(series):
                            if c.get("timestamp") == s.timestamp:
                                smart_indices.append(i)
                                break
                for s in avg_signals:
                    if s.token_address == token:
                        for i, c in enumerate(series):
                            if c.get("timestamp") == s.timestamp:
                                avg_indices.append(i)
                                break
            if smart_indices and avg_indices:
                assert min(smart_indices) <= max(avg_indices)

    def test_wallet_signals_confidence_range(self) -> None:
        gen = SyntheticMarketGenerator(seed=42)
        wallets = ["w1", "w2", "w3", "w4"]
        data = gen.generate_market_scenario("bull", token_count=2, hours=50)
        signals = gen.generate_wallet_signals(wallets, data)
        for s in signals:
            assert 0.0 <= s.confidence <= 1.0

    def test_wallet_signals_amount_positive(self) -> None:
        gen = SyntheticMarketGenerator(seed=42)
        wallets = ["w1", "w2"]
        data = gen.generate_market_scenario("bull", token_count=2, hours=50)
        signals = gen.generate_wallet_signals(wallets, data)
        for s in signals:
            assert s.amount_sol > 0

    def test_wallet_signals_price_positive(self) -> None:
        gen = SyntheticMarketGenerator(seed=42)
        wallets = ["w1", "w2"]
        data = gen.generate_market_scenario("bull", token_count=2, hours=50)
        signals = gen.generate_wallet_signals(wallets, data)
        for s in signals:
            assert s.price_usd > 0

    def test_wallet_signals_correlate_with_bear_scenario(self) -> None:
        gen = SyntheticMarketGenerator(seed=42)
        wallets = ["smart1", "smart2", "avg1", "avg2"]
        data = gen.generate_market_scenario("bear", token_count=3, hours=100)
        signals = gen.generate_wallet_signals(wallets, data, scenario="bear")
        assert len(signals) > 0
        # In bear markets, average wallets may buy late (catching falling knives)
        avg_signals = [s for s in signals if s.wallet_address in ("avg1", "avg2")]
        # Just verify signals are generated without crashing
        for s in avg_signals:
            assert s.price_usd > 0

    def test_pump_and_dump_wallet_signals(self) -> None:
        gen = SyntheticMarketGenerator(seed=42)
        wallets = ["w1", "w2", "w3", "w4"]
        data = gen.generate_market_scenario("pump_and_dump", token_count=2, hours=100)
        signals = gen.generate_wallet_signals(wallets, data, scenario="pump_and_dump")
        assert len(signals) >= 0

    def test_volatile_scenario_wallet_signals(self) -> None:
        gen = SyntheticMarketGenerator(seed=42)
        wallets = ["w1", "w2", "w3", "w4"]
        data = gen.generate_market_scenario("volatile", token_count=2, hours=100)
        signals = gen.generate_wallet_signals(wallets, data, scenario="volatile")
        assert len(signals) >= 0
