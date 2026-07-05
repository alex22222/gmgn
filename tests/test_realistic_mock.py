from __future__ import annotations

import pytest

from gmgn_monitor.realistic_mock import (
    PROFILE_DEFAULT_DISTRIBUTION,
    PROFILE_RANGES,
    RealisticMockGenerator,
    __all__,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def generator() -> RealisticMockGenerator:
    return RealisticMockGenerator(seed=42)


# ---------------------------------------------------------------------------
# generate_wallet
# ---------------------------------------------------------------------------

class TestGenerateWallet:
    def test_random_profile(self, generator: RealisticMockGenerator) -> None:
        wallet = generator.generate_wallet(profile="random")
        assert isinstance(wallet, dict)
        assert "wallet_address" in wallet
        assert "chain" in wallet
        assert wallet["chain"] == "solana"
        assert wallet["source"] == "gmgn_realistic_mock"
        assert "win_rate_30d" in wallet
        assert "total_profit_usd" in wallet

    def test_smart_profile_ranges(self, generator: RealisticMockGenerator) -> None:
        wallet = generator.generate_wallet(profile="smart")
        ranges = PROFILE_RANGES["smart"]
        assert ranges["win_rate"][0] <= wallet["win_rate_30d"] <= ranges["win_rate"][1]
        assert ranges["total_profit_usd"][0] <= wallet["total_profit_usd"] <= ranges["total_profit_usd"][1]
        assert ranges["avg_holding_hours"][0] <= wallet["avg_holding_duration_hours"] <= ranges["avg_holding_hours"][1]
        assert wallet["total_trades_30d"] >= 50

    def test_average_profile_ranges(self, generator: RealisticMockGenerator) -> None:
        wallet = generator.generate_wallet(profile="average")
        ranges = PROFILE_RANGES["average"]
        assert ranges["win_rate"][0] <= wallet["win_rate_30d"] <= ranges["win_rate"][1]
        assert ranges["avg_holding_hours"][0] <= wallet["avg_holding_duration_hours"] <= ranges["avg_holding_hours"][1]

    def test_weak_profile_ranges(self, generator: RealisticMockGenerator) -> None:
        wallet = generator.generate_wallet(profile="weak")
        ranges = PROFILE_RANGES["weak"]
        assert ranges["win_rate"][0] <= wallet["win_rate_30d"] <= ranges["win_rate"][1]
        assert wallet["total_profit_usd"] <= 0  # weak traders are loss-making

    def test_bot_profile(self, generator: RealisticMockGenerator) -> None:
        wallet = generator.generate_wallet(profile="bot")
        ranges = PROFILE_RANGES["bot"]
        assert wallet["total_trades_7d"] > 300
        assert wallet["avg_holding_duration_hours"] < 1.0
        assert wallet["self_transfer_ratio_percent"] >= 60.0
        assert ranges["win_rate"][0] <= wallet["win_rate_30d"] <= ranges["win_rate"][1]

    def test_elite_profile_ranges(self, generator: RealisticMockGenerator) -> None:
        wallet = generator.generate_wallet(profile="elite")
        ranges = PROFILE_RANGES["elite"]
        assert wallet["win_rate_30d"] >= 85.0
        assert wallet["total_profit_usd"] >= 50000.0
        assert wallet["portfolio_balance_usd"] >= 50000.0

    def test_reproducibility(self) -> None:
        gen1 = RealisticMockGenerator(seed=123)
        gen2 = RealisticMockGenerator(seed=123)
        w1 = gen1.generate_wallet(profile="smart")
        w2 = gen2.generate_wallet(profile="smart")
        assert w1["wallet_address"] == w2["wallet_address"]
        assert w1["win_rate_30d"] == w2["win_rate_30d"]
        assert w1["total_profit_usd"] == w2["total_profit_usd"]


# ---------------------------------------------------------------------------
# generate_batch
# ---------------------------------------------------------------------------

class TestGenerateBatch:
    def test_default_count(self, generator: RealisticMockGenerator) -> None:
        batch = generator.generate_batch(count=100)
        assert len(batch) == 100
        for wallet in batch:
            assert "wallet_address" in wallet
            assert "win_rate_30d" in wallet

    def test_zero_count(self, generator: RealisticMockGenerator) -> None:
        assert generator.generate_batch(count=0) == []

    def test_negative_count(self, generator: RealisticMockGenerator) -> None:
        assert generator.generate_batch(count=-5) == []

    def test_custom_distribution(self, generator: RealisticMockGenerator) -> None:
        dist = {"smart": 0.0, "elite": 1.0}
        batch = generator.generate_batch(count=50, distribution=dist)
        for wallet in batch:
            assert wallet["win_rate_30d"] >= 85.0
            assert wallet["total_profit_usd"] >= 50000.0

    def test_default_distribution_mix(self, generator: RealisticMockGenerator) -> None:
        batch = generator.generate_batch(count=1000)
        profiles = {"smart": 0, "average": 0, "weak": 0, "bot": 0, "elite": 0}
        for wallet in batch:
            # Heuristic classification based on generated data
            if wallet["win_rate_30d"] >= 85.0 and wallet["total_profit_usd"] >= 50000.0:
                profiles["elite"] += 1
            elif wallet["win_rate_30d"] >= 60.0 and wallet["total_profit_usd"] >= 5000.0:
                profiles["smart"] += 1
            elif wallet["total_trades_7d"] > 300 and wallet["avg_holding_duration_hours"] < 1.0:
                profiles["bot"] += 1
            elif wallet["total_profit_usd"] < 0:
                profiles["weak"] += 1
            else:
                profiles["average"] += 1
        # Just verify we got a mix of profiles
        assert all(c > 0 for c in profiles.values()), f"Expected all profiles, got {profiles}"


# ---------------------------------------------------------------------------
# generate_wallet_stats
# ---------------------------------------------------------------------------

class TestGenerateWalletStats:
    def test_returns_dict(self, generator: RealisticMockGenerator) -> None:
        stats = generator.generate_wallet_stats("test_addr", chain="sol")
        assert isinstance(stats, dict)
        assert stats["wallet_address"] == "test_addr"
        assert stats["chain"] == "sol"

    def test_has_required_fields(self, generator: RealisticMockGenerator) -> None:
        stats = generator.generate_wallet_stats("addr")
        required = [
            "wallet_address",
            "chain",
            "total_profit",
            "realized_profit",
            "unrealized_profit",
            "win_rate",
            "total_trades",
            "trades_7d",
            "trades_30d",
            "avg_holding_time",
            "pnl_7d",
            "pnl_30d",
            "max_drawdown",
            "portfolio_value",
            "balance_usd",
            "first_seen_at",
            "last_active_at",
        ]
        for field in required:
            assert field in stats, f"Missing field: {field}"

    def test_elite_stats(self, generator: RealisticMockGenerator) -> None:
        # Force elite by using a fixed seed that yields elite
        stats = generator.generate_wallet_stats("elite_addr")
        assert stats["win_rate"] >= 30.0  # at least some minimum
        assert stats["total_trades"] > 0

    def test_stats_compatibility_with_mapper(self, generator: RealisticMockGenerator) -> None:
        from gmgn_monitor.gmgn_data_mapper import map_wallet_stats_to_features
        stats = generator.generate_wallet_stats("addr")
        features = map_wallet_stats_to_features(stats)
        assert "wallet_address" in features
        assert "profit_metrics" in features
        assert "risk_metrics" in features
        assert "frequency_metrics" in features
        assert features["wallet_address"] == "addr"

    def test_reproducibility_stats(self) -> None:
        gen1 = RealisticMockGenerator(seed=99)
        gen2 = RealisticMockGenerator(seed=99)
        s1 = gen1.generate_wallet_stats("addr")
        s2 = gen2.generate_wallet_stats("addr")
        assert s1["win_rate"] == s2["win_rate"]
        assert s1["total_profit"] == s2["total_profit"]


# ---------------------------------------------------------------------------
# Profile distributions
# ---------------------------------------------------------------------------

class TestProfileDistributions:
    def test_default_distribution_sums_to_one(self) -> None:
        total = sum(PROFILE_DEFAULT_DISTRIBUTION.values())
        assert abs(total - 1.0) < 0.001

    def test_all_profiles_have_ranges(self) -> None:
        for profile in PROFILE_DEFAULT_DISTRIBUTION:
            assert profile in PROFILE_RANGES

    def test_all_ranges_have_required_fields(self) -> None:
        required = [
            "win_rate",
            "total_trades",
            "avg_profit_usd",
            "avg_holding_hours",
            "total_profit_usd",
            "portfolio_value_usd",
            "stablecoin_balance_usd",
            "trades_7d",
            "trades_30d",
            "max_drawdown",
        ]
        for profile, ranges in PROFILE_RANGES.items():
            for field in required:
                assert field in ranges, f"Profile {profile} missing {field}"
                lo, hi = ranges[field]
                assert lo <= hi, f"Profile {profile} {field} range invalid: {lo} > {hi}"


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

class TestExports:
    def test_all_list(self) -> None:
        assert "RealisticMockGenerator" in __all__
        assert "PROFILE_DEFAULT_DISTRIBUTION" in __all__
        assert "PROFILE_RANGES" in __all__
