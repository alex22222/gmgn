from __future__ import annotations
import pytest
from unittest.mock import patch
from gmgn_monitor.dry_run_executor import DryRunExecutor
from gmgn_monitor.trade_signal import TradeSignal, TPOrder, SLOrder
from gmgn_monitor.css_engine import CSSWeights
from gmgn_monitor.risk_manager import RiskLimits


class TestDryRunExecutor:
    def test_init_creates_modules(self):
        dre = DryRunExecutor(initial_balance_sol=10.0, wallet_scores={"w1": 100.0})
        assert dre.css_engine is not None
        assert dre.preprocessor is not None
        assert dre.risk_manager is not None
        assert dre.portfolio_tracker is not None
        assert dre.order_manager is not None

    def test_run_simulation_empty_signals(self):
        dre = DryRunExecutor(initial_balance_sol=10.0, wallet_scores={"w1": 100.0})
        result = dre.run_simulation([])
        assert result["orders_created"] == 0
        assert result["orders_confirmed"] == 0
        assert result["orders_failed"] == 0

    def test_run_simulation_valid_signals(self):
        dre = DryRunExecutor(initial_balance_sol=10.0, wallet_scores={"w1": 100.0})
        signals = [_make_signal(wallet="w1", token="t1")]
        with patch("gmgn_monitor.dry_run_executor.random.uniform", side_effect=[0.3, 0.02, 0.3, 0.02]):
            result = dre.run_simulation(signals)
        assert result["orders_created"] == 1
        assert result["orders_confirmed"] == 1
        assert result["orders_failed"] == 0
        assert len(result["execution_records"]) == 1

    def test_simulate_tp_sl_triggers_tp(self):
        dre = DryRunExecutor(initial_balance_sol=10.0, wallet_scores={"w1": 100.0})
        tp = TPOrder(level=1, trigger_percent=10.0, sell_percent=50.0)
        sl = SLOrder(trigger_percent=-10.0, sell_percent=100.0)
        signals = [_make_signal(wallet="w1", token="t1", tp_orders=(tp,), sl_order=sl)]
        with patch("gmgn_monitor.dry_run_executor.random.uniform", side_effect=[0.3, 0.02, 0.3, 0.02]):
            dre.run_simulation(signals)
        pos = dre.portfolio_tracker.get_position("t1")
        assert pos is not None
        result = dre.simulate_tp_sl(pos, [{"price_sol": 1.0}, {"price_sol": 1.2}])
        assert result["triggered_by"] == "TP"
        assert result["pnl_sol"] > 0

    def test_simulate_tp_sl_triggers_sl(self):
        dre = DryRunExecutor(initial_balance_sol=10.0, wallet_scores={"w1": 100.0})
        tp = TPOrder(level=1, trigger_percent=10.0, sell_percent=50.0)
        sl = SLOrder(trigger_percent=-10.0, sell_percent=100.0)
        signals = [_make_signal(wallet="w1", token="t1", tp_orders=(tp,), sl_order=sl)]
        with patch("gmgn_monitor.dry_run_executor.random.uniform", side_effect=[0.3, 0.02, 0.3, 0.02]):
            dre.run_simulation(signals)
        pos = dre.portfolio_tracker.get_position("t1")
        assert pos is not None
        result = dre.simulate_tp_sl(pos, [{"price_sol": 1.0}, {"price_sol": 0.8}])
        assert result["triggered_by"] == "SL"
        assert result["pnl_sol"] < 0

    def test_simulate_tp_sl_no_trigger(self):
        dre = DryRunExecutor(initial_balance_sol=10.0, wallet_scores={"w1": 100.0})
        tp = TPOrder(level=1, trigger_percent=10.0, sell_percent=50.0)
        sl = SLOrder(trigger_percent=-10.0, sell_percent=100.0)
        signals = [_make_signal(wallet="w1", token="t1", tp_orders=(tp,), sl_order=sl)]
        with patch("gmgn_monitor.dry_run_executor.random.uniform", side_effect=[0.3, 0.02, 0.3, 0.02]):
            dre.run_simulation(signals)
        pos = dre.portfolio_tracker.get_position("t1")
        assert pos is not None
        result = dre.simulate_tp_sl(pos, [{"price_sol": 1.0}, {"price_sol": 1.05}])
        assert result["triggered_by"] is None
        assert result["pnl_sol"] == pytest.approx(0.05 * pos.quantity, abs=0.01)

    def test_get_summary(self):
        dre = DryRunExecutor(initial_balance_sol=10.0, wallet_scores={"w1": 100.0})
        tp = TPOrder(level=1, trigger_percent=10.0, sell_percent=50.0)
        sl = SLOrder(trigger_percent=-10.0, sell_percent=100.0)
        signals = [_make_signal(wallet="w1", token="t1", tp_orders=(tp,), sl_order=sl)]
        with patch("gmgn_monitor.dry_run_executor.random.uniform", side_effect=[0.3, 0.02, 0.3, 0.02]):
            dre.run_simulation(signals)
        pos = dre.portfolio_tracker.get_position("t1")
        dre.simulate_tp_sl(pos, [{"price_sol": 1.0}, {"price_sol": 1.2}])
        summary = dre.get_summary()
        assert summary["total_trades"] > 0
        assert summary["win_rate"] == 1.0

    def test_reset(self):
        dre = DryRunExecutor(initial_balance_sol=10.0, wallet_scores={"w1": 100.0})
        signals = [_make_signal(wallet="w1", token="t1")]
        with patch("gmgn_monitor.dry_run_executor.random.uniform", side_effect=[0.3, 0.02, 0.3, 0.02]):
            dre.run_simulation(signals)
        dre.reset()
        assert dre.portfolio_tracker.get_snapshot().total_value_sol == 10.0
        assert dre.order_manager.get_stats().total_orders == 0
        assert dre._total_signals == 0
        assert len(dre._execution_records) == 0

    def test_to_execution(self):
        dre = DryRunExecutor(initial_balance_sol=10.0, wallet_scores={"w1": 100.0})
        signal = _make_signal()
        order = dre.order_manager.create_order(signal)
        with patch("gmgn_monitor.dry_run_executor.random.uniform", side_effect=[0.3, 0.02, 0.3, 0.02]):
            execution = dre.to_execution(order)
        assert execution.dry_run is True
        assert execution.actual_amount_sol > 0
        assert execution.actual_slippage_percent > 0

    def test_end_to_end_signals_orders_tp_summary(self):
        dre = DryRunExecutor(initial_balance_sol=10.0, wallet_scores={"w1": 100.0})
        tp = TPOrder(level=1, trigger_percent=10.0, sell_percent=50.0)
        sl = SLOrder(trigger_percent=-10.0, sell_percent=100.0)
        signals = [_make_signal(wallet="w1", token="t1", tp_orders=(tp,), sl_order=sl)]
        with patch("gmgn_monitor.dry_run_executor.random.uniform", side_effect=[0.3, 0.02, 0.3, 0.02]):
            dre.run_simulation(signals)
        pos = dre.portfolio_tracker.get_position("t1")
        dre.simulate_tp_sl(pos, [{"price_sol": 1.0}, {"price_sol": 1.2}])
        summary = dre.get_summary()
        assert summary["total_trades"] > 0


# Helpers

def _make_signal(
    wallet: str = "wallet1",
    token: str = "token1",
    tp_orders: tuple = (),
    sl_order: SLOrder | None = None,
) -> TradeSignal:
    return TradeSignal(
        signal_id=f"sig-{wallet}-{token}",
        wallet_address=wallet,
        target_token=token,
        signal_type="NEW_POSITION",
        urgency_score=50,
        confidence_score=50,
        quality_score=60,
        recommended_amount_sol=1.0,
        tp_orders=tp_orders,
        sl_order=sl_order,
    )
