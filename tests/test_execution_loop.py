import pytest
from datetime import datetime, timezone
from gmgn_monitor.execution_loop import (
    ExecutionLoopEngine,
    LoopMetrics,
    MarketData,
)
from gmgn_monitor.css_engine import CSSEngine
from gmgn_monitor.signal_preprocessor import SignalPreprocessor
from gmgn_monitor.risk_manager import RiskManager, RiskLimits
from gmgn_monitor.order_manager import OrderManager
from gmgn_monitor.portfolio_tracker import PortfolioTracker
from gmgn_monitor.trade_signal import TradeSignal


class TestExecutionLoopEngine:
    def test_run_cycle_empty_signals_returns_zero(self):
        engine = _make_engine()
        result = engine.run_cycle([], {})
        assert result["processed_count"] == 0
        assert result["accepted_count"] == 0
        assert result["css_pass_count"] == 0
        assert result["risk_allow_count"] == 0
        assert result["orders_created"] == []

    def test_run_cycle_valid_signals_produces_funnel(self):
        engine = _make_engine()
        signals = [_make_signal(wallet="w1", token="t1")]
        wallet_scores = {"w1": 100.0}
        result = engine.run_cycle(signals, wallet_scores)
        assert result["processed_count"] == 1
        assert result["accepted_count"] == 1
        assert result["css_pass_count"] == 1
        assert result["risk_allow_count"] == 1
        assert len(result["orders_created"]) == 1

    def test_run_cycle_does_not_create_buy_order_for_exit_signal(self):
        engine = _make_engine()
        signals = [_make_signal(wallet="w1", token="t1", signal_type="EXIT")]
        wallet_scores = {"w1": 100.0}
        result = engine.run_cycle(signals, wallet_scores)
        assert result["processed_count"] == 1
        assert result["orders_created"] == []
        assert result["risk_allow_count"] == 0
        assert result["execution_log"][2]["sell_only_count"] == 1

    def test_get_metrics_returns_history(self):
        engine = _make_engine()
        engine.run_cycle([_make_signal(wallet="w1", token="t1")], {"w1": 100.0})
        metrics = engine.get_metrics()
        assert len(metrics) == 1
        assert metrics[0].signals_in == 1
        assert metrics[0].orders_created == 1

    def test_reset_metrics_clears_history(self):
        engine = _make_engine()
        engine.run_cycle([_make_signal(wallet="w1", token="t1")], {"w1": 100.0})
        engine.reset_metrics()
        assert engine.get_metrics() == []


class TestMarketData:
    def test_default_fields(self):
        md = MarketData()
        assert md.token_risk_scores == {}
        assert md.market_condition.btc_trend_24h == 0.0
        assert md.market_condition.overall_sentiment == 50.0
        assert md.market_condition.fear_greed_index == 50.0
        assert md.time_momentum.signal_age_seconds == 0.0
        assert md.time_momentum.chain_activity_score == 50.0
        assert md.time_momentum.volume_surge_1h == 0.0

    def test_custom_fields(self):
        md = MarketData(
            token_risk_scores={"t1": None},
            market_condition=None,
            time_momentum=None,
        )
        assert md.token_risk_scores == {"t1": None}


class TestLoopMetrics:
    def test_fields_and_to_dict(self):
        lm = LoopMetrics(
            signals_in=5,
            preprocessed_out=4,
            css_pass=3,
            risk_allow=2,
            orders_created=1,
            cycle_duration_ms=12.34,
        )
        assert lm.signals_in == 5
        assert lm.preprocessed_out == 4
        assert lm.css_pass == 3
        assert lm.risk_allow == 2
        assert lm.orders_created == 1
        assert lm.cycle_duration_ms == 12.34
        d = lm.to_dict()
        assert d["signals_in"] == 5
        assert d["preprocessed_out"] == 4
        assert d["css_pass"] == 3
        assert d["risk_allow"] == 2
        assert d["orders_created"] == 1
        assert d["cycle_duration_ms"] == 12.34
        assert "timestamp" in d


# Helpers

def _make_engine() -> ExecutionLoopEngine:
    return ExecutionLoopEngine(
        css_engine=CSSEngine(),
        preprocessor=SignalPreprocessor(),
        risk_manager=RiskManager(
            RiskLimits(
                daily_loss_limit_percent=5.0,
                max_single_position_percent=20.0,
                max_total_positions=5,
                default_stop_loss_percent=10.0,
            )
        ),
        order_manager=OrderManager(),
        portfolio_tracker=PortfolioTracker(initial_balance_sol=10.0),
    )


def _make_signal(
    wallet: str = "wallet1",
    token: str = "token1",
    signal_type: str = "NEW_POSITION",
) -> TradeSignal:
    return TradeSignal(
        signal_id=f"sig-{wallet}-{token}",
        wallet_address=wallet,
        target_token=token,
        signal_type=signal_type,
        urgency_score=50,
        confidence_score=50,
        quality_score=60,
        recommended_amount_sol=1.0,
        received_at=datetime.utcnow(),
    )
