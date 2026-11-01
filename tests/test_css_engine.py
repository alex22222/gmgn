import unittest

import pytest
from datetime import datetime, timedelta, timezone
from gmgn_monitor.css_engine import (
    CSSWeights,
    AccountState,
    TokenRiskScore,
    MarketCondition,
    TimeMomentum,
    CSSDecision,
    CSSResult,
    CSSEngine,
)
from gmgn_monitor.trade_signal import TradeSignal


class TestCSSWeights:
    def test_default_weights_sum_to_one(self):
        weights = CSSWeights.default_weights()
        total = weights.wallet + weights.token_risk + weights.market_condition + weights.account_state + weights.time_momentum
        assert total == pytest.approx(1.0, abs=0.01)

    def test_invalid_weights_raise(self):
        with pytest.raises(ValueError):
            CSSWeights(0.1, 0.1, 0.1, 0.1, 0.1)


class TestAccountState:
    def test_can_trade_false_when_daily_loss_exceeded(self):
        acc = AccountState(
            balance_sol=10.0,
            open_positions_count=0,
            daily_pnl_sol=-6.0,
            daily_loss_limit_sol=5.0,
            max_positions=5,
        )
        assert acc.can_trade is False

    def test_can_trade_false_when_positions_maxed(self):
        acc = AccountState(
            balance_sol=10.0,
            open_positions_count=5,
            daily_pnl_sol=0.0,
            daily_loss_limit_sol=5.0,
            max_positions=5,
        )
        assert acc.can_trade is False

    def test_can_trade_true_when_ok(self):
        acc = AccountState(
            balance_sol=10.0,
            open_positions_count=4,
            daily_pnl_sol=-1.0,
            daily_loss_limit_sol=5.0,
            max_positions=5,
        )
        assert acc.can_trade is True


class TestCSSDecisionThresholds:
    def test_score_70_and_can_trade_is_pass(self):
        assert CSSEngine().evaluate(
            signal=_make_signal(),
            wallet_score=100.0,
            token_risk=_make_token_risk(),
            market=_make_market(),
            account=_make_account(can_trade=True),
            momentum=_make_momentum(),
        ).decision == CSSDecision.PASS

    def test_score_69_9_and_can_trade_is_watch(self):
        engine = CSSEngine(CSSWeights(1.0, 0.0, 0.0, 0.0, 0.0))
        result = engine.evaluate(
            signal=_make_signal(),
            wallet_score=69.9,
            token_risk=_make_token_risk(),
            market=_make_market(),
            account=_make_account(can_trade=True),
            momentum=_make_momentum(),
        )
        assert result.css_score == pytest.approx(69.9, abs=0.1)
        assert result.decision == CSSDecision.WATCH

    def test_score_49_9_and_can_trade_is_reject(self):
        engine = CSSEngine(CSSWeights(1.0, 0.0, 0.0, 0.0, 0.0))
        result = engine.evaluate(
            signal=_make_signal(),
            wallet_score=49.9,
            token_risk=_make_token_risk(),
            market=_make_market(),
            account=_make_account(can_trade=True),
            momentum=_make_momentum(),
        )
        assert result.css_score == pytest.approx(49.9, abs=0.1)
        assert result.decision == CSSDecision.REJECT

    def test_can_trade_false_always_reject(self):
        engine = CSSEngine()
        result = engine.evaluate(
            signal=_make_signal(),
            wallet_score=100.0,
            token_risk=_make_token_risk(),
            market=_make_market(),
            account=_make_account(can_trade=False),
            momentum=_make_momentum(),
        )
        assert result.decision == CSSDecision.REJECT


class TestCSSEngineEvaluate:
    def test_evaluate_with_all_dimensions(self):
        engine = CSSEngine()
        result = engine.evaluate(
            signal=_make_signal(),
            wallet_score=80.0,
            token_risk=TokenRiskScore(liquidity_score=70.0, contract_safe=True, market_cap_usd=1_000_000.0, holder_count=5_000),
            market=MarketCondition(btc_trend_24h=5.0, overall_sentiment=60.0, fear_greed_index=55.0),
            account=AccountState(balance_sol=10.0, open_positions_count=0, daily_pnl_sol=0.0, daily_loss_limit_sol=5.0, max_positions=5),
            momentum=TimeMomentum(signal_age_seconds=30.0, chain_activity_score=70.0, volume_surge_1h=20.0),
        )
        assert isinstance(result, CSSResult)
        assert 0.0 <= result.css_score <= 100.0
        assert result.can_trade is True

    def test_evaluate_result_properties(self):
        result = CSSEngine().evaluate(
            signal=_make_signal(),
            wallet_score=50.0,
            token_risk=_make_token_risk(),
            market=_make_market(),
            account=_make_account(can_trade=True),
            momentum=_make_momentum(),
        )
        assert result.is_pass or result.is_watch or result.is_reject
        assert result.is_pass is (result.decision == CSSDecision.PASS)
        assert result.is_watch is (result.decision == CSSDecision.WATCH)
        assert result.is_reject is (result.decision == CSSDecision.REJECT)


class TestCSSEngineOrderLines(unittest.TestCase):
    def test_default_lines_stay_70_and_50(self):
        engine = CSSEngine(CSSWeights(1.0, 0.0, 0.0, 0.0, 0.0))
        self.assertEqual(engine.pass_score, 70.0)
        self.assertEqual(engine.watch_score, 50.0)
        watched = engine.evaluate(
            signal=_make_signal(),
            wallet_score=69.9,
            token_risk=_make_token_risk(),
            market=_make_market(),
            account=_make_account(can_trade=True),
            momentum=_make_momentum(),
        )
        passed = engine.evaluate(
            signal=_make_signal(),
            wallet_score=70.0,
            token_risk=_make_token_risk(),
            market=_make_market(),
            account=_make_account(can_trade=True),
            momentum=_make_momentum(),
        )
        self.assertEqual(watched.decision, CSSDecision.WATCH)
        self.assertEqual(passed.decision, CSSDecision.PASS)

    def test_custom_lines_split_pass_watch_and_reject(self):
        engine = CSSEngine(CSSWeights(1.0, 0.0, 0.0, 0.0, 0.0), pass_score=60, watch_score=45)
        passed = engine.evaluate(
            signal=_make_signal(),
            wallet_score=60.0,
            token_risk=_make_token_risk(),
            market=_make_market(),
            account=_make_account(can_trade=True),
            momentum=_make_momentum(),
        )
        watched = engine.evaluate(
            signal=_make_signal(),
            wallet_score=59.9,
            token_risk=_make_token_risk(),
            market=_make_market(),
            account=_make_account(can_trade=True),
            momentum=_make_momentum(),
        )
        rejected = engine.evaluate(
            signal=_make_signal(),
            wallet_score=44.9,
            token_risk=_make_token_risk(),
            market=_make_market(),
            account=_make_account(can_trade=True),
            momentum=_make_momentum(),
        )
        self.assertEqual(passed.decision, CSSDecision.PASS)
        self.assertEqual(watched.decision, CSSDecision.WATCH)
        self.assertEqual(rejected.decision, CSSDecision.REJECT)

    def test_inverted_lines_raise(self):
        with self.assertRaises(ValueError):
            CSSEngine(pass_score=40, watch_score=50)


class TestTokenRiskNormalization:
    def test_contract_safe_false_lowers_score(self):
        engine = CSSEngine()
        safe = engine._normalize_token_risk(
            TokenRiskScore(liquidity_score=80.0, contract_safe=True, market_cap_usd=1_000_000.0, holder_count=5_000)
        )
        unsafe = engine._normalize_token_risk(
            TokenRiskScore(liquidity_score=80.0, contract_safe=False, market_cap_usd=1_000_000.0, holder_count=5_000)
        )
        assert unsafe < safe
        assert unsafe == pytest.approx(safe - 30.0, abs=0.1)


class TestMarketConditionNormalization:
    def test_btc_trend_negative_maps_to_zero(self):
        engine = CSSEngine()
        score = engine._normalize_market_condition(MarketCondition(btc_trend_24h=-20.0, overall_sentiment=50.0, fear_greed_index=50.0))
        assert score == pytest.approx(30.0, abs=0.1)

    def test_btc_trend_zero_maps_to_fifty(self):
        engine = CSSEngine()
        score = engine._normalize_market_condition(MarketCondition(btc_trend_24h=0.0, overall_sentiment=50.0, fear_greed_index=50.0))
        assert score == pytest.approx(50.0, abs=0.1)

    def test_btc_trend_positive_maps_to_one_hundred(self):
        engine = CSSEngine()
        score = engine._normalize_market_condition(MarketCondition(btc_trend_24h=20.0, overall_sentiment=50.0, fear_greed_index=50.0))
        assert score == pytest.approx(70.0, abs=0.1)

    def test_btc_trend_clamped_to_0_100(self):
        engine = CSSEngine()
        low = engine._normalize_market_condition(MarketCondition(btc_trend_24h=-100.0, overall_sentiment=0.0, fear_greed_index=0.0))
        assert low == pytest.approx(0.0, abs=0.1)
        high = engine._normalize_market_condition(MarketCondition(btc_trend_24h=100.0, overall_sentiment=100.0, fear_greed_index=100.0))
        assert high == pytest.approx(100.0, abs=0.1)


# Helpers

def _make_signal() -> TradeSignal:
    return TradeSignal(
        signal_id="sig-1",
        wallet_address="wallet1",
        target_token="token1",
        signal_type="NEW_POSITION",
        urgency_score=50,
        confidence_score=50,
        quality_score=50,
        recommended_amount_sol=1.0,
    )


def _make_token_risk() -> TokenRiskScore:
    return TokenRiskScore(liquidity_score=100.0, contract_safe=True, market_cap_usd=10_000_000.0, holder_count=100_000)


def _make_market() -> MarketCondition:
    return MarketCondition(btc_trend_24h=0.0, overall_sentiment=50.0, fear_greed_index=50.0)


def _make_account(can_trade: bool = True) -> AccountState:
    if can_trade:
        return AccountState(balance_sol=10.0, open_positions_count=0, daily_pnl_sol=0.0, daily_loss_limit_sol=5.0, max_positions=5)
    else:
        return AccountState(balance_sol=10.0, open_positions_count=5, daily_pnl_sol=0.0, daily_loss_limit_sol=5.0, max_positions=5)


def _make_momentum() -> TimeMomentum:
    return TimeMomentum(signal_age_seconds=0.0, chain_activity_score=50.0, volume_surge_1h=0.0)
