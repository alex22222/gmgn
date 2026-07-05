import pytest
from datetime import datetime
from unittest.mock import patch
from gmgn_monitor.order_manager import OrderManager, Order, OrderStats, ExecutionLog
from gmgn_monitor.trade_signal import TradeSignal


class TestOrderManager:
    def test_create_order_pending(self):
        om = OrderManager()
        signal = _make_signal()
        order = om.create_order(signal)
        assert order.status == "PENDING"
        assert order.token_address == signal.target_token
        assert order.amount_sol == signal.recommended_amount_sol

    def test_submit_order(self):
        om = OrderManager()
        signal = _make_signal()
        order = om.create_order(signal)
        submitted = om.submit_order(order.order_id, tx_hash="tx123")
        assert submitted.status == "SUBMITTED"
        assert submitted.tx_hash == "tx123"
        assert submitted.submitted_at is not None

    def test_confirm_order(self):
        om = OrderManager()
        signal = _make_signal()
        order = om.create_order(signal)
        om.submit_order(order.order_id)
        confirmed = om.confirm_order(order.order_id, actual_amount=0.9, actual_slippage=0.3, gas_cost=0.02)
        assert confirmed.status == "CONFIRMED"
        assert confirmed.confirmed_at is not None

    def test_fail_order(self):
        om = OrderManager()
        signal = _make_signal()
        order = om.create_order(signal)
        failed = om.fail_order(order.order_id, "network error")
        assert failed.status == "FAILED"
        assert failed.retry_count == 1
        assert failed.error_message == "network error"

    def test_retry_order_creates_new_pending(self):
        om = OrderManager(max_retries=3)
        signal = _make_signal()
        order = om.create_order(signal)
        om.fail_order(order.order_id, "error")
        new_order = om.retry_order(order.order_id)
        assert new_order is not None
        assert new_order.status == "PENDING"
        assert new_order.retry_count == 1

    def test_retry_order_none_when_max_retries_exceeded(self):
        om = OrderManager(max_retries=1)
        signal = _make_signal()
        order = om.create_order(signal)
        om.fail_order(order.order_id, "error")
        assert om.retry_order(order.order_id) is None

    def test_cancel_order(self):
        om = OrderManager()
        signal = _make_signal()
        order = om.create_order(signal)
        cancelled = om.cancel_order(order.order_id)
        assert cancelled.status == "CANCELLED"

    def test_get_stats(self):
        om = OrderManager()
        s1 = _make_signal()
        o1 = om.create_order(s1)
        om.submit_order(o1.order_id)
        om.confirm_order(o1.order_id, actual_amount=0.9, actual_slippage=0.3, gas_cost=0.02)

        s2 = _make_signal()
        o2 = om.create_order(s2)
        om.fail_order(o2.order_id, "error")

        stats = om.get_stats()
        assert stats.total_orders == 2
        assert stats.confirmed == 1
        assert stats.failed == 1
        assert stats.success_rate == 0.5

    def test_list_orders_filtered(self):
        om = OrderManager()
        s1 = _make_signal()
        o1 = om.create_order(s1)
        om.submit_order(o1.order_id)
        om.confirm_order(o1.order_id, actual_amount=0.9, actual_slippage=0.3, gas_cost=0.02)

        s2 = _make_signal()
        o2 = om.create_order(s2)
        om.fail_order(o2.order_id, "error")

        confirmed = om.list_orders(status="CONFIRMED")
        assert len(confirmed) == 1
        assert confirmed[0].status == "CONFIRMED"

    def test_get_order_invalid_returns_none(self):
        om = OrderManager()
        assert om.get_order("nonexistent") is None

    def test_submit_order_invalid_raises(self):
        om = OrderManager()
        with pytest.raises(ValueError):
            om.submit_order("nonexistent")

    def test_to_dict_on_order(self):
        order = Order(
            order_id="id1",
            signal_id="sig1",
            token_address="t1",
            amount_sol=1.0,
            status="PENDING",
        )
        d = order.to_dict()
        assert d["order_id"] == "id1"

    def test_to_dict_on_order_stats(self):
        stats = OrderStats(total_orders=5, confirmed=3, success_rate=0.6)
        d = stats.to_dict()
        assert d["success_rate"] == 0.6

    def test_to_dict_on_execution_log(self):
        log = ExecutionLog(
            log_id="l1",
            order_id="o1",
            action="submit",
            timestamp=datetime.utcnow(),
        )
        d = log.to_dict()
        assert d["action"] == "submit"


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
