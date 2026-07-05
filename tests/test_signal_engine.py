from __future__ import annotations

import pytest

from gmgn_monitor.signal_engine import SignalEngine
from gmgn_monitor.backtest_strategies import BuySignal


# ─────────────────────────── Fixtures ───────────────────────────

@pytest.fixture
def sample_wallet_scores() -> dict[str, float]:
    return {
        "wallet1": 85.0,
        "wallet2": 72.0,
        "wallet3": 55.0,
        "wallet4": 90.0,
    }


@pytest.fixture
def sample_wallet_activity() -> dict[str, list[dict]]:
    return {
        "wallet1": [
            {"token_address": "TOKEN_A", "action": "buy", "price": 1.0, "amount": 0.5, "timestamp": "2025-07-01T10:00:00Z"},
            {"token_address": "TOKEN_B", "action": "buy", "price": 2.0, "amount": 1.0, "timestamp": "2025-07-01T11:00:00Z"},
            {"token_address": "TOKEN_A", "action": "sell", "price": 1.5, "amount": 0.5, "timestamp": "2025-07-01T12:00:00Z"},
        ],
        "wallet2": [
            {"token_address": "TOKEN_A", "action": "buy", "price": 1.1, "amount": 0.6, "timestamp": "2025-07-01T10:30:00Z"},
            {"token_address": "TOKEN_C", "action": "buy", "price": 3.0, "amount": 0.8, "timestamp": "2025-07-01T11:30:00Z"},
        ],
        "wallet3": [
            {"token_address": "TOKEN_A", "action": "buy", "price": 1.2, "amount": 0.4, "timestamp": "2025-07-01T11:00:00Z"},
        ],
    }


# ─────────────────────────── Tests ───────────────────────────

class TestSignalEngine:
    def test_initialization(self, sample_wallet_scores: dict[str, float]) -> None:
        engine = SignalEngine(sample_wallet_scores)
        assert engine.wallet_scores == sample_wallet_scores

    def test_extract_buy_signals(self, sample_wallet_scores: dict[str, float], sample_wallet_activity: dict[str, list[dict]]) -> None:
        engine = SignalEngine(sample_wallet_scores)
        signals = engine.extract_buy_signals(sample_wallet_activity)
        assert len(signals) == 5  # 2 from wallet1 + 2 from wallet2 + 1 from wallet3 (sell excluded)
        for signal in signals:
            assert isinstance(signal, BuySignal)
            assert signal.wallet_address in sample_wallet_scores

    def test_extract_buy_signals_filters_non_buy(self, sample_wallet_scores: dict[str, float], sample_wallet_activity: dict[str, list[dict]]) -> None:
        engine = SignalEngine(sample_wallet_scores)
        signals = engine.extract_buy_signals(sample_wallet_activity)
        sell_signals = [s for s in signals if s.wallet_address == "wallet1" and s.token_address == "TOKEN_A" and s.timestamp == "2025-07-01T12:00:00Z"]
        assert len(sell_signals) == 0

    def test_filter_signals_by_wallet_score(self, sample_wallet_scores: dict[str, float], sample_wallet_activity: dict[str, list[dict]]) -> None:
        engine = SignalEngine(sample_wallet_scores)
        signals = engine.extract_buy_signals(sample_wallet_activity)
        filtered = engine.filter_signals_by_wallet_score(signals, min_score=60.0)
        assert all(sample_wallet_scores[s.wallet_address] >= 60.0 for s in filtered)
        # wallet3 has score 55, so its signals should be excluded
        wallet3_signals = [s for s in filtered if s.wallet_address == "wallet3"]
        assert len(wallet3_signals) == 0

    def test_filter_signals_by_wallet_score_high_threshold(self, sample_wallet_scores: dict[str, float], sample_wallet_activity: dict[str, list[dict]]) -> None:
        engine = SignalEngine(sample_wallet_scores)
        signals = engine.extract_buy_signals(sample_wallet_activity)
        filtered = engine.filter_signals_by_wallet_score(signals, min_score=80.0)
        assert all(sample_wallet_scores[s.wallet_address] >= 80.0 for s in filtered)
        # Only wallet1 (85) and wallet4 (90) should remain, but wallet4 has no activity
        assert all(s.wallet_address in {"wallet1", "wallet4"} for s in filtered)

    def test_group_signals_by_token(self, sample_wallet_scores: dict[str, float], sample_wallet_activity: dict[str, list[dict]]) -> None:
        engine = SignalEngine(sample_wallet_scores)
        signals = engine.extract_buy_signals(sample_wallet_activity)
        grouped = engine.group_signals_by_token(signals)
        assert "TOKEN_A" in grouped
        assert "TOKEN_B" in grouped
        assert "TOKEN_C" in grouped
        assert len(grouped["TOKEN_A"]) == 3
        assert len(grouped["TOKEN_B"]) == 1
        assert len(grouped["TOKEN_C"]) == 1

    def test_group_signals_by_token_empty(self, sample_wallet_scores: dict[str, float]) -> None:
        engine = SignalEngine(sample_wallet_scores)
        grouped = engine.group_signals_by_token([])
        assert grouped == {}

    def test_find_consensus_signals(self, sample_wallet_scores: dict[str, float], sample_wallet_activity: dict[str, list[dict]]) -> None:
        engine = SignalEngine(sample_wallet_scores)
        signals = engine.extract_buy_signals(sample_wallet_activity)
        consensus = engine.find_consensus_signals(signals, min_wallets=3, time_window_hours=6)
        assert len(consensus) == 1
        assert consensus[0].token_address == "TOKEN_A"
        assert consensus[0].wallet_address == "consensus"

    def test_find_consensus_signals_not_enough_wallets(self, sample_wallet_scores: dict[str, float], sample_wallet_activity: dict[str, list[dict]]) -> None:
        engine = SignalEngine(sample_wallet_scores)
        signals = engine.extract_buy_signals(sample_wallet_activity)
        consensus = engine.find_consensus_signals(signals, min_wallets=5, time_window_hours=6)
        assert len(consensus) == 0

    def test_find_consensus_signals_outside_time_window(self, sample_wallet_scores: dict[str, float]) -> None:
        engine = SignalEngine(sample_wallet_scores)
        activity = {
            "wallet1": [
                {"token_address": "TOKEN_X", "action": "buy", "price": 1.0, "amount": 0.5, "timestamp": "2025-07-01T10:00:00Z"},
            ],
            "wallet2": [
                {"token_address": "TOKEN_X", "action": "buy", "price": 1.1, "amount": 0.6, "timestamp": "2025-07-01T20:00:00Z"},
            ],
            "wallet3": [
                {"token_address": "TOKEN_X", "action": "buy", "price": 1.2, "amount": 0.4, "timestamp": "2025-07-01T21:00:00Z"},
            ],
        }
        signals = engine.extract_buy_signals(activity)
        consensus = engine.find_consensus_signals(signals, min_wallets=3, time_window_hours=6)
        assert len(consensus) == 0

    def test_calculate_signal_confidence(self, sample_wallet_scores: dict[str, float], sample_wallet_activity: dict[str, list[dict]]) -> None:
        engine = SignalEngine(sample_wallet_scores)
        signals = engine.extract_buy_signals(sample_wallet_activity)
        recalculated = engine.calculate_signal_confidence(signals)
        assert len(recalculated) == len(signals)
        for s in recalculated:
            assert 0.0 <= s.confidence <= 1.0

    def test_calculate_signal_confidence_with_consensus_boost(self, sample_wallet_scores: dict[str, float], sample_wallet_activity: dict[str, list[dict]]) -> None:
        engine = SignalEngine(sample_wallet_scores)
        signals = engine.extract_buy_signals(sample_wallet_activity)
        recalculated = engine.calculate_signal_confidence(signals)
        # TOKEN_A has 3 wallets, so signals for TOKEN_A should have higher confidence
        token_a_signals = [s for s in recalculated if s.token_address == "TOKEN_A"]
        token_b_signals = [s for s in recalculated if s.token_address == "TOKEN_B"]
        if token_a_signals and token_b_signals:
            assert token_a_signals[0].confidence >= token_b_signals[0].confidence

    def test_empty_data(self, sample_wallet_scores: dict[str, float]) -> None:
        engine = SignalEngine(sample_wallet_scores)
        signals = engine.extract_buy_signals({})
        assert signals == []
        filtered = engine.filter_signals_by_wallet_score(signals)
        assert filtered == []
        grouped = engine.group_signals_by_token(signals)
        assert grouped == {}
        consensus = engine.find_consensus_signals(signals)
        assert consensus == []

    def test_no_consensus_single_wallet(self, sample_wallet_scores: dict[str, float]) -> None:
        activity = {
            "wallet1": [
                {"token_address": "TOKEN_A", "action": "buy", "price": 1.0, "amount": 0.5, "timestamp": "2025-07-01T10:00:00Z"},
            ],
        }
        engine = SignalEngine(sample_wallet_scores)
        signals = engine.extract_buy_signals(activity)
        consensus = engine.find_consensus_signals(signals, min_wallets=3)
        assert len(consensus) == 0

    def test_single_wallet_multiple_tokens(self, sample_wallet_scores: dict[str, float]) -> None:
        activity = {
            "wallet1": [
                {"token_address": "TOKEN_A", "action": "buy", "price": 1.0, "amount": 0.5, "timestamp": "2025-07-01T10:00:00Z"},
                {"token_address": "TOKEN_B", "action": "buy", "price": 2.0, "amount": 1.0, "timestamp": "2025-07-01T11:00:00Z"},
            ],
        }
        engine = SignalEngine(sample_wallet_scores)
        signals = engine.extract_buy_signals(activity)
        assert len(signals) == 2
        grouped = engine.group_signals_by_token(signals)
        assert len(grouped) == 2

    def test_consensus_with_direction_field(self, sample_wallet_scores: dict[str, float]) -> None:
        activity = {
            "wallet1": [
                {"token_address": "TOKEN_A", "direction": "buy", "price": 1.0, "amount_sol": 0.5, "timestamp": "2025-07-01T10:00:00Z"},
            ],
            "wallet2": [
                {"token_address": "TOKEN_A", "direction": "buy", "price": 1.1, "amount_sol": 0.6, "timestamp": "2025-07-01T10:30:00Z"},
            ],
            "wallet3": [
                {"token_address": "TOKEN_A", "direction": "buy", "price": 1.2, "amount_sol": 0.4, "timestamp": "2025-07-01T11:00:00Z"},
            ],
        }
        engine = SignalEngine(sample_wallet_scores)
        signals = engine.extract_buy_signals(activity)
        assert len(signals) == 3
        consensus = engine.find_consensus_signals(signals, min_wallets=3, time_window_hours=6)
        assert len(consensus) == 1
