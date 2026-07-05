from __future__ import annotations
import pytest
from datetime import datetime, timedelta
from gmgn_monitor.signal_preprocessor import SignalPreprocessor, PreprocessResult, PreprocessStats
from gmgn_monitor.trade_signal import TradeSignal


class TestSignalPreprocessor:
    def test_deduplication_keeps_highest_quality(self):
        sp = SignalPreprocessor(dedup_window_seconds=300.0)
        base_time = datetime.utcnow()
        s1 = _make_signal(wallet="w1", token="t1", quality=60, received_at=base_time)
        s2 = _make_signal(wallet="w1", token="t1", quality=70, received_at=base_time + timedelta(seconds=10))
        result = sp.process([s1, s2], wallet_scores={"w1": 60.0})
        assert len(result.accepted) == 1
        assert result.accepted[0].quality_score == 70
        assert result.stats.deduplicated == 1

    def test_blacklist_filtering(self):
        sp = SignalPreprocessor(blacklist_tokens={"bad_token"}, blacklist_wallets={"bad_wallet"})
        good = _make_signal(wallet="good", token="good")
        bad_token = _make_signal(wallet="good", token="bad_token")
        bad_wallet = _make_signal(wallet="bad_wallet", token="good")
        result = sp.process([good, bad_token, bad_wallet], wallet_scores={"good": 60.0, "bad_wallet": 60.0})
        assert len(result.accepted) == 1
        assert result.accepted[0].target_token == "good"
        assert result.stats.blacklisted == 2

    def test_quality_gate(self):
        sp = SignalPreprocessor(min_confidence=50)
        low = _make_signal(quality=40)
        high = _make_signal(quality=60)
        result = sp.process([low, high], wallet_scores={"wallet1": 60.0})
        assert len(result.accepted) == 1
        assert result.accepted[0].quality_score == 60
        assert result.stats.below_quality == 1

    def test_wallet_score_gate(self):
        sp = SignalPreprocessor(min_wallet_score=55.0)
        s1 = _make_signal(wallet="w1")
        s2 = _make_signal(wallet="w2")
        result = sp.process([s1, s2], wallet_scores={"w1": 40.0, "w2": 70.0})
        assert len(result.accepted) == 1
        assert result.accepted[0].wallet_address == "w2"
        assert result.stats.below_wallet_score == 1

    def test_expiry_filter(self):
        sp = SignalPreprocessor()
        fresh = _make_signal()
        expired = _make_signal(expires_at=datetime.utcnow() - timedelta(minutes=1))
        result = sp.process([fresh, expired], wallet_scores={"wallet1": 60.0})
        assert len(result.accepted) == 1
        assert result.accepted[0].is_expired() is False
        assert result.stats.expired == 1

    def test_cumulative_stats(self):
        sp = SignalPreprocessor()
        sp.process([_make_signal(quality=80)], wallet_scores={"wallet1": 60.0})
        sp.process([_make_signal(quality=80, wallet="w2")], wallet_scores={"wallet1": 60.0, "w2": 60.0})
        assert sp.stats.total_processed == 2
        assert sp.stats.accepted == 2

    def test_reset_dedup_state(self):
        sp = SignalPreprocessor(dedup_window_seconds=300.0)
        base_time = datetime.utcnow()
        s1 = _make_signal(wallet="w1", token="t1", quality=60, received_at=base_time)
        sp.process([s1], wallet_scores={"w1": 60.0})
        sp.reset_dedup_state()
        s2 = _make_signal(wallet="w1", token="t1", quality=60, received_at=base_time + timedelta(seconds=10))
        result = sp.process([s2], wallet_scores={"w1": 60.0})
        assert result.stats.deduplicated == 0
        assert len(result.accepted) == 1

    def test_dedup_window_expired(self):
        sp = SignalPreprocessor(dedup_window_seconds=10.0)
        base_time = datetime.utcnow()
        s1 = _make_signal(wallet="w1", token="t1", quality=60, received_at=base_time)
        sp.process([s1], wallet_scores={"w1": 60.0})
        s2 = _make_signal(wallet="w1", token="t1", quality=60, received_at=base_time + timedelta(seconds=11))
        result = sp.process([s2], wallet_scores={"w1": 60.0})
        assert result.stats.deduplicated == 0
        assert len(result.accepted) == 1


# Helpers

def _make_signal(
    wallet: str = "wallet1",
    token: str = "token1",
    quality: int = 60,
    received_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> TradeSignal:
    if received_at is None:
        received_at = datetime.utcnow()
    if expires_at is None:
        expires_at = datetime.utcnow() + timedelta(minutes=10)
    return TradeSignal(
        signal_id=f"sig-{wallet}-{token}-{quality}",
        wallet_address=wallet,
        target_token=token,
        signal_type="NEW_POSITION",
        urgency_score=50,
        confidence_score=50,
        quality_score=quality,
        recommended_amount_sol=1.0,
        received_at=received_at,
        expires_at=expires_at,
    )
