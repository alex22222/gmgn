import pytest
from datetime import datetime, timedelta
from gmgn_monitor.risk_manager import RiskManager, RiskLimits, RiskCheckResult, CircuitBreakerState
from gmgn_monitor.trade_signal import TradeSignal


class TestRiskLimits:
    def test_to_dict(self):
        limits = RiskLimits(
            daily_loss_limit_percent=5.0,
            max_single_position_percent=20.0,
            max_total_positions=5,
            default_stop_loss_percent=10.0,
        )
        d = limits.to_dict()
        assert d["daily_loss_limit_percent"] == 5.0
        assert d["max_single_position_percent"] == 20.0
        assert d["max_total_positions"] == 5
        assert d["default_stop_loss_percent"] == 10.0


class TestCircuitBreakerState:
    def test_to_dict(self):
        cb = CircuitBreakerState(triggered=True, triggered_at=datetime.utcnow(), reason="test", consecutive_failed_trades=2)
        d = cb.to_dict()
        assert d["triggered"] is True
        assert d["reason"] == "test"
        assert d["consecutive_failed_trades"] == 2


class TestRiskManagerChecks:
    def test_daily_loss_limit_blocks(self):
        limits = RiskLimits(daily_loss_limit_percent=5.0, max_single_position_percent=20.0, max_total_positions=5, default_stop_loss_percent=10.0)
        rm = RiskManager(limits)
        rm.update_daily_pnl(-10.0)
        signal = _make_signal(amount=1.0)
        result = rm.check_trade(signal, current_portfolio_value=100.0, open_positions=[])
        assert result == RiskCheckResult.BLOCK

    def test_max_position_size_blocks(self):
        limits = RiskLimits(daily_loss_limit_percent=5.0, max_single_position_percent=10.0, max_total_positions=5, default_stop_loss_percent=10.0)
        rm = RiskManager(limits)
        signal = _make_signal(amount=15.0)
        result = rm.check_trade(signal, current_portfolio_value=100.0, open_positions=[])
        assert result == RiskCheckResult.BLOCK

    def test_max_positions_blocks(self):
        limits = RiskLimits(daily_loss_limit_percent=5.0, max_single_position_percent=20.0, max_total_positions=2, default_stop_loss_percent=10.0)
        rm = RiskManager(limits)
        signal = _make_signal(amount=1.0)
        result = rm.check_trade(signal, current_portfolio_value=100.0, open_positions=[{}, {}])
        assert result == RiskCheckResult.BLOCK

    def test_kill_switch_blocks(self):
        limits = RiskLimits(daily_loss_limit_percent=5.0, max_single_position_percent=20.0, max_total_positions=5, default_stop_loss_percent=10.0)
        rm = RiskManager(limits)
        rm.activate_kill_switch("emergency")
        signal = _make_signal(amount=1.0)
        result = rm.check_trade(signal, current_portfolio_value=100.0, open_positions=[])
        assert result == RiskCheckResult.BLOCK

    def test_circuit_breaker_trigger_and_reset(self):
        limits = RiskLimits(daily_loss_limit_percent=5.0, max_single_position_percent=20.0, max_total_positions=5, default_stop_loss_percent=10.0)
        rm = RiskManager(limits)
        rm.trigger_circuit_breaker("test")
        assert rm.is_circuit_breaker_active() is True
        rm.reset_circuit_breaker()
        assert rm.is_circuit_breaker_active() is False

    def test_circuit_breaker_auto_trigger_after_three_failures(self):
        limits = RiskLimits(daily_loss_limit_percent=5.0, max_single_position_percent=20.0, max_total_positions=5, default_stop_loss_percent=10.0)
        rm = RiskManager(limits)
        rm.record_trade_result(False)
        rm.record_trade_result(False)
        rm.record_trade_result(False)
        assert rm.is_circuit_breaker_active() is True

    def test_check_trade_allow(self):
        limits = RiskLimits(daily_loss_limit_percent=5.0, max_single_position_percent=20.0, max_total_positions=5, default_stop_loss_percent=10.0)
        rm = RiskManager(limits)
        signal = _make_signal(amount=1.0)
        result = rm.check_trade(signal, current_portfolio_value=100.0, open_positions=[])
        assert result == RiskCheckResult.ALLOW

    def test_check_trade_warn(self):
        limits = RiskLimits(daily_loss_limit_percent=5.0, max_single_position_percent=20.0, max_total_positions=5, default_stop_loss_percent=10.0)
        rm = RiskManager(limits)
        signal = _make_signal(amount=1.0, max_slippage=60, confidence=20)
        result = rm.check_trade(signal, current_portfolio_value=100.0, open_positions=[])
        assert result == RiskCheckResult.WARN

    def test_to_dict_on_risk_limits(self):
        limits = RiskLimits(daily_loss_limit_percent=5.0, max_single_position_percent=20.0, max_total_positions=5, default_stop_loss_percent=10.0)
        d = limits.to_dict()
        assert "daily_loss_limit_percent" in d

    def test_to_dict_on_circuit_breaker(self):
        cb = CircuitBreakerState()
        d = cb.to_dict()
        assert "triggered" in d


# Helpers

def _make_signal(amount: float = 1.0, max_slippage: float = 30.0, confidence: int = 50) -> TradeSignal:
    return TradeSignal(
        signal_id="sig-1",
        wallet_address="wallet1",
        target_token="token1",
        signal_type="NEW_POSITION",
        urgency_score=50,
        confidence_score=confidence,
        quality_score=50,
        recommended_amount_sol=amount,
        max_slippage_percent=max_slippage,
    )
