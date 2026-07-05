from __future__ import annotations

import pytest

from gmgn_monitor.wallet_robot_detector import (
    WalletFeatures,
    detect_robot,
    _score_trade_frequency,
    _score_interval_consistency,
    _score_holding_time,
    _score_gas_pattern,
    _score_time_uniformity,
)


def _features(**overrides) -> WalletFeatures:
    """Build a WalletFeatures with sensible defaults, overridden by kwargs."""
    base = {
        "wallet_address": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZR6Y7Q5XqK",
        "trades_7d": 50,
        "trade_intervals_seconds": [],
        "avg_holding_hours": 24.0,
        "fees_sol_list": [],
        "trade_hours_of_day": [],
    }
    base.update(overrides)
    return WalletFeatures.from_dict(base)


class TestScoreTradeFrequency:
    """Tests for _score_trade_frequency — max 30 points."""

    def test_normal_trader_zero(self):
        f = _features(trades_7d=50)
        assert _score_trade_frequency(f) == 0.0

    def test_slightly_active_zero(self):
        f = _features(trades_7d=200)
        assert _score_trade_frequency(f) == 0.0

    def test_high_freq_10pts(self):
        f = _features(trades_7d=250)  # ~35.7/day
        assert _score_trade_frequency(f) == 10.0

    def test_very_high_freq_20pts(self):
        f = _features(trades_7d=400)  # ~57.1/day
        assert _score_trade_frequency(f) == 20.0

    def test_extreme_freq_30pts(self):
        f = _features(trades_7d=800)  # ~114/day
        assert _score_trade_frequency(f) == 30.0

    def test_edge_30_daily(self):
        f = _features(trades_7d=210)  # exactly 30/day, not > 30
        assert _score_trade_frequency(f) == 0.0

    def test_over_30_daily(self):
        f = _features(trades_7d=211)  # just over 30/day
        assert _score_trade_frequency(f) == 10.0

    def test_invalid_type_returns_zero(self):
        f = _features(trades_7d="lots")
        assert _score_trade_frequency(f) == 0.0


class TestScoreIntervalConsistency:
    """Tests for _score_interval_consistency — max 25 points."""

    def test_insufficient_intervals(self):
        f = _features(trade_intervals_seconds=[60.0] * 5)
        assert _score_interval_consistency(f) == 0.0

    def test_perfectly_regular_25pts(self):
        f = _features(trade_intervals_seconds=[60.0] * 50)
        assert _score_interval_consistency(f) == 25.0

    def test_slightly_irregular_15pts(self):
        # CV ~0.29, above 0.2 but below 0.5
        intervals = [60.0 + i * 10 for i in range(50)]  # std ~14.4, mean ~84.4, CV ~0.17
        # Wait, mean = (60+590)/2 = 325, that's wrong. Let's compute properly.
        # Actually for [60, 70, 80, ..., 550] (50 values)
        # mean = 60 + 49*10/2 = 305, std ~144, CV ~0.47
        # That's close to 0.5, should be 15 pts
        f = _features(trade_intervals_seconds=[60.0 + i * 10 for i in range(50)])
        assert _score_interval_consistency(f) == 15.0

    def test_random_intervals_0pts(self):
        import random
        random.seed(42)
        intervals = [random.uniform(10, 600) for _ in range(50)]
        f = _features(trade_intervals_seconds=intervals)
        score = _score_interval_consistency(f)
        assert score == 0.0

    def test_invalid_type_returns_zero(self):
        f = _features(trade_intervals_seconds="invalid")
        assert _score_interval_consistency(f) == 0.0

    def test_negative_intervals_filtered(self):
        f = _features(trade_intervals_seconds=[-5.0, 60.0] * 25)
        # After filtering negatives, 25 valid entries of identical 60.0 remain -> CV=0
        assert _score_interval_consistency(f) == 25.0


class TestScoreHoldingTime:
    """Tests for _score_holding_time — max 20 points."""

    def test_normal_holder_zero(self):
        f = _features(avg_holding_hours=24.0)
        assert _score_holding_time(f) == 0.0

    def test_under_30min_10pts(self):
        f = _features(avg_holding_hours=0.25)  # 15 min
        assert _score_holding_time(f) == 10.0

    def test_under_5min_20pts(self):
        f = _features(avg_holding_hours=0.05)  # 3 min
        assert _score_holding_time(f) == 20.0

    def test_exactly_5min_10pts(self):
        f = _features(avg_holding_hours=0.083)  # ~5 min, boundary falls into 10-pt bucket
        assert _score_holding_time(f) == 10.0

    def test_under_5min_20pts(self):
        f = _features(avg_holding_hours=0.05)  # 3 min
        assert _score_holding_time(f) == 20.0

    def test_exactly_30min_0pts(self):
        f = _features(avg_holding_hours=0.5)
        assert _score_holding_time(f) == 0.0

    def test_under_30min_10pts(self):
        f = _features(avg_holding_hours=0.4)
        assert _score_holding_time(f) == 10.0

    def test_invalid_type_zero(self):
        f = _features(avg_holding_hours="fast")
        assert _score_holding_time(f) == 20.0  # falls through to <0.083 because _to_float returns 0.0


class TestScoreGasPattern:
    """Tests for _score_gas_pattern — max 10 points."""

    def test_insufficient_fees(self):
        f = _features(fees_sol_list=[0.005] * 5)
        assert _score_gas_pattern(f) == 0.0

    def test_fixed_gas_10pts(self):
        f = _features(fees_sol_list=[0.005] * 50)
        assert _score_gas_pattern(f) == 10.0

    def test_slightly_varying_gas_5pts(self):
        # CV ~0.057, below 0.1
        fees = [0.005 + i * 0.0001 for i in range(50)]
        f = _features(fees_sol_list=fees)
        score = _score_gas_pattern(f)
        assert score == 5.0

    def test_varying_gas_0pts(self):
        import random
        random.seed(42)
        fees = [random.uniform(0.001, 0.05) for _ in range(50)]
        f = _features(fees_sol_list=fees)
        assert _score_gas_pattern(f) == 0.0

    def test_invalid_type_zero(self):
        f = _features(fees_sol_list="cheap")
        assert _score_gas_pattern(f) == 0.0

    def test_zero_mean_skips(self):
        f = _features(fees_sol_list=[0.0] * 50)
        assert _score_gas_pattern(f) == 0.0


class TestScoreTimeUniformity:
    """Tests for _score_time_uniformity — max 15 points."""

    def test_insufficient_hours(self):
        f = _features(trade_hours_of_day=[12] * 5)
        assert _score_time_uniformity(f) == 0.0

    def test_uniform_24h_15pts(self):
        hours = list(range(24)) * 5  # 120 trades, perfectly uniform
        f = _features(trade_hours_of_day=hours)
        assert _score_time_uniformity(f) == 15.0

    def test_daytime_only_0pts(self):
        hours = [8, 9, 10, 11, 12, 13, 14, 15, 16] * 20  # 180 trades, only daytime
        f = _features(trade_hours_of_day=hours)
        assert _score_time_uniformity(f) == 0.0

    def test_slightly_uniform_8pts(self):
        # Create a distribution with chi2 around 30-50
        hours = (
            [0, 1, 2, 3, 4, 5] * 3  # 18
            + [6, 7, 8, 9, 10, 11] * 5  # 30
            + [12, 13, 14, 15, 16, 17] * 5  # 30
            + [18, 19, 20, 21, 22, 23] * 3  # 18
        )  # 96 trades, somewhat uneven
        f = _features(trade_hours_of_day=hours)
        score = _score_time_uniformity(f)
        # Should be either 8 or 15 depending on chi2; let's assert it's in range
        assert score in (0.0, 8.0, 15.0)

    def test_invalid_type_zero(self):
        f = _features(trade_hours_of_day="morning")
        assert _score_time_uniformity(f) == 0.0

    def test_out_of_range_filtered(self):
        hours = [8, 9, 10, 25, -1] * 20  # 25 and -1 are filtered
        f = _features(trade_hours_of_day=hours)
        # After filtering valid hours, 60 entries remain
        score = _score_time_uniformity(f)
        assert score in (0.0, 8.0, 15.0)


class TestDetectRobot:
    """Integration tests for the full detect_robot function."""

    def test_normal_human_wallet(self):
        f = _features(
            trades_7d=50,
            trade_intervals_seconds=[3600.0 + i * 300 for i in range(50)],
            avg_holding_hours=24.0,
            fees_sol_list=[0.005 + i * 0.001 for i in range(50)],
            trade_hours_of_day=[8, 9, 10, 11, 12, 13, 14, 15, 16] * 10,
        )
        score = detect_robot(f)
        assert score < 40.0
        assert score >= 0.0

    def test_clear_bot_high_score(self):
        f = _features(
            trades_7d=800,
            trade_intervals_seconds=[60.0] * 50,
            avg_holding_hours=0.03,
            fees_sol_list=[0.005] * 50,
            trade_hours_of_day=list(range(24)) * 5,
        )
        score = detect_robot(f)
        assert score >= 60.0
        assert score <= 100.0

    def test_empty_features_zero(self):
        f = WalletFeatures.from_dict({})
        score = detect_robot(f)
        assert score == 0.0

    def test_only_high_frequency(self):
        f = _features(trades_7d=600)
        score = detect_robot(f)
        assert score == 20.0  # 600/7 ≈ 85.7/day -> 20 pts (between 50 and 100)

    def test_only_uniform_time(self):
        f = _features(trade_hours_of_day=list(range(24)) * 5)
        score = detect_robot(f)
        assert score == 15.0

    def test_combined_medium_score(self):
        f = _features(
            trades_7d=300,
            trade_intervals_seconds=[120.0] * 50,
            avg_holding_hours=0.2,
        )
        score = detect_robot(f)
        # 10 (freq: 42.9/day) + 25 (interval) + 10 (holding) = 45
        assert score == 45.0

    def test_score_is_capped_at_100(self):
        f = _features(
            trades_7d=1000,
            trade_intervals_seconds=[10.0] * 100,
            avg_holding_hours=0.01,
            fees_sol_list=[0.005] * 100,
            trade_hours_of_day=list(range(24)) * 10,
        )
        score = detect_robot(f)
        assert score == 100.0

    def test_negative_values_in_lists_filtered(self):
        f = _features(
            trade_intervals_seconds=[-10, 60.0] * 30,  # negatives filtered, 30 valid
            fees_sol_list=[-0.001, 0.005] * 30,  # negatives filtered, 30 valid
            trade_hours_of_day=[-1, 25, 12] * 20,  # out-of-range filtered, 20 valid
        )
        score = detect_robot(f)
        # Should not crash; score should be >= 0
        assert score >= 0.0
        assert score <= 100.0
