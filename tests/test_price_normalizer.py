from __future__ import annotations

from datetime import datetime, timezone

import pytest

from gmgn_monitor.price_normalizer import (
    normalize_birdeye_ohlcv,
    normalize_helius_price_history,
    normalize_dexscreener_ohlcv,
    fill_missing_ohlcv,
    resample_ohlcv,
)


class TestNormalizeBirdeyeOhlcv:
    """Tests for Birdeye OHLCV normalization."""

    def test_normalize_birdeye_list_with_full_keys(self):
        raw = [
            {
                "unixTime": 1704067200,
                "open": 100.0,
                "high": 105.0,
                "low": 98.0,
                "close": 102.0,
                "volume": 50000.0,
            }
        ]
        result = normalize_birdeye_ohlcv(raw)
        assert len(result) == 1
        assert result[0]["timestamp"] == "2024-01-01T00:00:00Z"
        assert result[0]["open"] == 100.0
        assert result[0]["high"] == 105.0
        assert result[0]["low"] == 98.0
        assert result[0]["close"] == 102.0
        assert result[0]["volume"] == 50000.0

    def test_normalize_birdeye_with_short_keys(self):
        raw = [
            {"unixTime": 1704067200, "o": 100.0, "h": 105.0, "l": 98.0, "c": 102.0, "v": 50000.0}
        ]
        result = normalize_birdeye_ohlcv(raw)
        assert len(result) == 1
        assert result[0]["open"] == 100.0
        assert result[0]["close"] == 102.0
        assert result[0]["volume"] == 50000.0

    def test_normalize_birdeye_nested_data_items(self):
        raw = {
            "data": {
                "items": [
                    {"unixTime": 1704067200, "o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "v": 1000.0}
                ]
            }
        }
        result = normalize_birdeye_ohlcv(raw)
        assert len(result) == 1
        assert result[0]["close"] == 1.5

    def test_normalize_birdeye_direct_items(self):
        raw = {
            "items": [
                {"unixTime": 1704067200, "o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "v": 1000.0}
            ]
        }
        result = normalize_birdeye_ohlcv(raw)
        assert len(result) == 1
        assert result[0]["close"] == 1.5

    def test_normalize_birdeye_with_string_timestamp(self):
        raw = [
            {"timestamp": "2025-01-01T00:00:00Z", "open": 100.0, "close": 101.0}
        ]
        result = normalize_birdeye_ohlcv(raw)
        assert len(result) == 1
        assert result[0]["timestamp"] == "2025-01-01T00:00:00Z"

    def test_normalize_birdeye_empty_response(self):
        assert normalize_birdeye_ohlcv([]) == []
        assert normalize_birdeye_ohlcv({}) == []
        assert normalize_birdeye_ohlcv(None) == []

    def test_normalize_birdeye_invalid_data(self):
        raw = [
            {"not_a_timestamp": 123},
            {"unixTime": "not_a_number", "open": 100.0},
        ]
        result = normalize_birdeye_ohlcv(raw)
        assert result == []

    def test_normalize_birdeye_missing_fields(self):
        raw = [
            {"unixTime": 1704067200, "close": 100.0}
        ]
        result = normalize_birdeye_ohlcv(raw)
        assert len(result) == 1
        assert result[0]["timestamp"] == "2024-01-01T00:00:00Z"
        assert result[0]["close"] == 100.0
        assert result[0]["open"] is None
        assert result[0]["high"] is None
        assert result[0]["low"] is None
        assert result[0]["volume"] is None


class TestNormalizeHeliusPriceHistory:
    """Tests for Helius price history normalization."""

    def test_normalize_helius_simple_list(self):
        raw = [
            {"timestamp": "2025-01-01T00:00:00Z", "price": 1.5},
            {"timestamp": "2025-01-01T01:00:00Z", "price": 1.6},
        ]
        result = normalize_helius_price_history(raw)
        assert len(result) == 2
        assert result[0]["timestamp"] == "2025-01-01T00:00:00Z"
        assert result[0]["close"] == 1.5
        assert result[0]["open"] == 1.5
        assert result[0]["high"] == 1.5
        assert result[0]["low"] == 1.5
        assert result[0]["volume"] == 0.0

    def test_normalize_helius_with_unix_time(self):
        raw = [
            {"unixTime": 1704067200, "price": 2.0},
        ]
        result = normalize_helius_price_history(raw)
        assert len(result) == 1
        assert result[0]["timestamp"] == "2024-01-01T00:00:00Z"
        assert result[0]["close"] == 2.0

    def test_normalize_helius_dict_wrapper(self):
        raw = {"items": [{"timestamp": "2025-01-01T00:00:00Z", "price": 3.0}]}
        result = normalize_helius_price_history(raw)
        assert len(result) == 1
        assert result[0]["close"] == 3.0

    def test_normalize_helius_empty(self):
        assert normalize_helius_price_history([]) == []
        assert normalize_helius_price_history({}) == []
        assert normalize_helius_price_history(None) == []

    def test_normalize_helius_invalid_items(self):
        raw = [
            {"timestamp": "2025-01-01T00:00:00Z"},  # missing price
            {"price": 1.5},  # missing timestamp
        ]
        result = normalize_helius_price_history(raw)
        assert result == []


class TestNormalizeDexscreenerOhlcv:
    """Tests for DexScreener OHLCV normalization."""

    def test_normalize_dexscreener_simple(self):
        raw = [
            {"unixTime": 1704067200, "priceUsd": 10.0, "volumeUsd": 5000.0}
        ]
        result = normalize_dexscreener_ohlcv(raw)
        assert len(result) == 1
        assert result[0]["close"] == 10.0
        assert result[0]["volume"] == 5000.0

    def test_normalize_dexscreener_with_ohlc_keys(self):
        raw = [
            {"unixTime": 1704067200, "open": 9.0, "high": 11.0, "low": 8.0, "close": 10.0, "volume": 5000.0}
        ]
        result = normalize_dexscreener_ohlcv(raw)
        assert len(result) == 1
        assert result[0]["open"] == 9.0
        assert result[0]["high"] == 11.0
        assert result[0]["low"] == 8.0
        assert result[0]["close"] == 10.0

    def test_normalize_dexscreener_empty(self):
        assert normalize_dexscreener_ohlcv([]) == []
        assert normalize_dexscreener_ohlcv({}) == []

    def test_normalize_dexscreener_pairs_wrapper(self):
        raw = {
            "pairs": [
                {"unixTime": 1704067200, "priceUsd": 5.0}
            ]
        }
        result = normalize_dexscreener_ohlcv(raw)
        assert len(result) == 1
        assert result[0]["close"] == 5.0


class TestFillMissingOhlcv:
    """Tests for missing OHLCV data filling."""

    def test_fill_no_gaps(self):
        ohlcv = [
            {"timestamp": "2025-01-01T00:00:00Z", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
            {"timestamp": "2025-01-01T01:00:00Z", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
        ]
        result = fill_missing_ohlcv(ohlcv, expected_hours=2)
        assert len(result) == 2

    def test_fill_one_gap(self):
        ohlcv = [
            {"timestamp": "2025-01-01T00:00:00Z", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
            {"timestamp": "2025-01-01T02:00:00Z", "open": 102, "high": 103, "low": 101, "close": 102, "volume": 1000},
        ]
        result = fill_missing_ohlcv(ohlcv, expected_hours=3)
        assert len(result) == 3
        # The middle candle should be forward-filled
        assert result[1]["timestamp"] == "2025-01-01T01:00:00Z"
        assert result[1]["close"] == 100.0
        assert result[1]["open"] == 100.0
        assert result[1]["high"] == 100.0
        assert result[1]["low"] == 100.0
        assert result[1]["volume"] == 0.0

    def test_fill_empty(self):
        assert fill_missing_ohlcv([], expected_hours=10) == []

    def test_fill_single_candle(self):
        ohlcv = [
            {"timestamp": "2025-01-01T00:00:00Z", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
        ]
        result = fill_missing_ohlcv(ohlcv, expected_hours=1)
        assert len(result) == 1
        assert result[0]["close"] == 100.0


class TestResampleOhlcv:
    """Tests for OHLCV resampling."""

    def test_resample_1h_to_4h(self):
        ohlcv = [
            {"timestamp": "2025-01-01T00:00:00Z", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
            {"timestamp": "2025-01-01T01:00:00Z", "open": 100, "high": 102, "low": 98, "close": 101, "volume": 1000},
            {"timestamp": "2025-01-01T02:00:00Z", "open": 101, "high": 103, "low": 100, "close": 102, "volume": 1000},
            {"timestamp": "2025-01-01T03:00:00Z", "open": 102, "high": 104, "low": 101, "close": 103, "volume": 1000},
        ]
        result = resample_ohlcv(ohlcv, "4H")
        assert len(result) == 1
        assert result[0]["open"] == 100
        assert result[0]["high"] == 104
        assert result[0]["low"] == 98
        assert result[0]["close"] == 103
        assert result[0]["volume"] == 4000.0

    def test_resample_1h_to_1d(self):
        ohlcv = [
            {"timestamp": "2025-01-01T00:00:00Z", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
            {"timestamp": "2025-01-01T01:00:00Z", "open": 100, "high": 102, "low": 98, "close": 101, "volume": 1000},
            {"timestamp": "2025-01-01T02:00:00Z", "open": 101, "high": 103, "low": 100, "close": 102, "volume": 1000},
            {"timestamp": "2025-01-01T03:00:00Z", "open": 102, "high": 104, "low": 101, "close": 103, "volume": 1000},
        ]
        result = resample_ohlcv(ohlcv, "1D")
        assert len(result) == 1
        assert result[0]["open"] == 100
        assert result[0]["high"] == 104
        assert result[0]["low"] == 98
        assert result[0]["close"] == 103
        assert result[0]["volume"] == 4000.0

    def test_resample_empty(self):
        assert resample_ohlcv([], "4H") == []

    def test_resample_invalid_timeframe(self):
        ohlcv = [
            {"timestamp": "2025-01-01T00:00:00Z", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
        ]
        # Unknown timeframe defaults to 1H (pass-through)
        result = resample_ohlcv(ohlcv, "unknown")
        assert len(result) == 1

    def test_resample_multiple_days(self):
        ohlcv = [
            {"timestamp": "2025-01-01T00:00:00Z", "open": 100, "high": 110, "low": 90, "close": 105, "volume": 1000},
            {"timestamp": "2025-01-01T12:00:00Z", "open": 105, "high": 115, "low": 95, "close": 110, "volume": 1000},
            {"timestamp": "2025-01-02T00:00:00Z", "open": 110, "high": 120, "low": 100, "close": 115, "volume": 1000},
            {"timestamp": "2025-01-02T12:00:00Z", "open": 115, "high": 125, "low": 105, "close": 120, "volume": 1000},
        ]
        result = resample_ohlcv(ohlcv, "1D")
        assert len(result) == 2
        assert result[0]["high"] == 115
        assert result[0]["low"] == 90
        assert result[1]["high"] == 125
        assert result[1]["low"] == 100


class TestEdgeCases:
    """Edge case and error handling tests."""

    def test_birdeye_non_numeric_values(self):
        raw = [
            {"unixTime": 1704067200, "open": "not_a_number", "close": 100.0}
        ]
        result = normalize_birdeye_ohlcv(raw)
        assert len(result) == 1
        assert result[0]["open"] is None
        assert result[0]["close"] == 100.0

    def test_helius_non_numeric_price(self):
        raw = [
            {"timestamp": "2025-01-01T00:00:00Z", "price": "not_a_number"}
        ]
        result = normalize_helius_price_history(raw)
        assert result == []

    def test_fill_missing_with_invalid_timestamps(self):
        ohlcv = [
            {"timestamp": "not-a-date", "open": 100, "close": 100, "volume": 1000},
        ]
        result = fill_missing_ohlcv(ohlcv, expected_hours=1)
        assert result == []
