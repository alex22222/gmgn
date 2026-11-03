from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

from gmgn_monitor.copy_risk import CopyRiskProfile
from gmgn_monitor.order_manager import OrderManager
from gmgn_monitor.portfolio_tracker import PortfolioTracker
from gmgn_monitor.real_trade_executor import RealTradeExecutor
from gmgn_monitor.risk_manager import RiskManager
from gmgn_monitor.sell_executor import SellExecutor, SellSignal
from gmgn_monitor.trade_signal import TradeSignal


class _SwapClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def swap(self, params):
        self.calls.append(params)
        return {"tx_hash": "tx-live"}


def _signal(amount: float, slippage: float = 2.0) -> TradeSignal:
    return TradeSignal(
        signal_id="sig-1",
        wallet_address="Leader111",
        target_token="Token111",
        signal_type="NEW_POSITION",
        urgency_score=70,
        confidence_score=70,
        quality_score=70,
        recommended_amount_sol=amount,
        max_slippage_percent=slippage,
    )


def _executor(gate: dict, *, auto_confirm: bool = True) -> tuple[RealTradeExecutor, _SwapClient]:
    client = _SwapClient()
    executor = RealTradeExecutor.__new__(RealTradeExecutor)
    executor._auto_confirm = auto_confirm
    executor._copy_risk = CopyRiskProfile()
    executor._gate_override = gate
    executor._portfolio = PortfolioTracker(initial_balance_sol=10.0)
    executor._risk_limits = executor._copy_risk.to_risk_limits()
    executor._risk_manager = RiskManager(executor._risk_limits)
    executor._order_manager = OrderManager()
    executor._client = client
    executor._chain = "sol"
    executor._wallet_address = "Wallet111"
    return executor, client


class LiveTradeGuardTests(unittest.TestCase):
    def test_closed_gate_does_not_swap_even_with_auto_confirm(self):
        executor, client = _executor({})
        result = executor.execute_trade(_signal(0.01))

        self.assertFalse(result.success)
        self.assertEqual(result.error_message, "automation gate is blocked")
        self.assertEqual(client.calls, [])

    def test_oversize_order_does_not_swap_when_gate_is_open(self):
        executor, client = _executor({"force_open": True})
        result = executor.execute_trade(_signal(0.02))

        self.assertFalse(result.success)
        self.assertEqual(result.error_message, "exceeds max_single_trade_sol")
        self.assertEqual(client.calls, [])

    def test_daily_loss_blocks_a_tiny_live_buy(self):
        executor, client = _executor({"force_open": True})
        executor._portfolio._daily_pnl_sol = -0.03
        result = executor.execute_trade(_signal(0.01))

        self.assertFalse(result.success)
        self.assertEqual(result.error_message, "daily loss limit")
        self.assertEqual(client.calls, [])

    def test_open_gate_tiny_order_can_swap_when_auto_confirm_is_armed(self):
        executor, client = _executor({"force_open": True})
        result = executor.execute_trade(_signal(0.01))

        self.assertTrue(result.success)
        self.assertEqual(result.tx_hash, "tx-live")
        self.assertEqual(client.calls[0]["input_amount"], "10000000")
        self.assertEqual(client.calls[0]["input_token"], RealTradeExecutor.SOL_TOKEN_ADDRESS)

    def test_closed_gate_does_not_prompt_or_swap(self):
        executor, client = _executor({}, auto_confirm=False)

        def fail_input(_prompt: str) -> str:
            raise AssertionError("closed gate must not ask for confirmation")

        with patch("builtins.input", fail_input):
            result = executor.execute_trade(_signal(0.01))

        self.assertEqual(result.error_message, "automation gate is blocked")
        self.assertEqual(client.calls, [])

    def test_closed_gate_blocks_live_sell_before_swap(self):
        executor = SellExecutor.__new__(SellExecutor)
        executor._auto_confirm = True
        executor._copy_risk = CopyRiskProfile()
        executor._gate_override = {}
        client = _SwapClient()
        executor._client = client

        def fail_balance(_token: str) -> float:
            raise AssertionError("closed gate must not read a balance or swap")

        with patch.object(executor, "get_token_balance", fail_balance):
            result = executor.execute_sell(SellSignal(
                signal_id="sell-1",
                token_address="Token111",
                sell_percent=100.0,
                trigger_type="COPY_EXIT",
                max_slippage_percent=2.0,
            ))

        self.assertFalse(result.success)
        self.assertEqual(result.error_message, "automation gate is blocked")
        self.assertEqual(client.calls, [])


def _load_script_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_auto_copy_trading.py"
    spec = importlib.util.spec_from_file_location("run_auto_copy_trading_guard", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _real_config(*, auto_confirm: bool) -> dict:
    return {
        "trade_mode": "real",
        "global_settings": {"copy_trading_enabled": True, "auto_confirm": auto_confirm},
        "wallets": [{
            "wallet_address": "Leader111",
            "mode": "follow",
            "enabled": True,
            "total_score": 80,
            "risk_limits": {"max_single_trade_sol": 0.01, "stop_loss_percent": -40},
        }],
    }


class RealCopyRunnerTests(unittest.TestCase):
    def test_real_init_arms_tiny_auto_confirm_only_when_gate_is_open(self):
        module = _load_script_module()
        with patch.object(module, "RealTradeExecutor", return_value=object()) as buy, \
             patch.object(module, "SellExecutor", return_value=object()) as sell, \
             patch.object(module, "load_automation_gate", return_value={"force_open": True}):
            components = module._init_components(
                _real_config(auto_confirm=True),
                "test-key",
                "pem",
                wallet_address="Wallet111",
                trade_mode="real",
            )

        self.assertTrue(buy.call_args.kwargs["auto_confirm"])
        self.assertTrue(sell.call_args.kwargs["auto_confirm"])
        self.assertNotIn("gate_config", buy.call_args.kwargs)
        self.assertTrue(components["tiny_auto_confirm"])

    def test_real_init_keeps_prompt_when_gate_is_closed(self):
        module = _load_script_module()
        with patch.object(module, "RealTradeExecutor", return_value=object()) as buy, \
             patch.object(module, "SellExecutor", return_value=object()) as sell, \
             patch.object(module, "load_automation_gate", return_value={}):
            components = module._init_components(
                _real_config(auto_confirm=True),
                "test-key",
                "pem",
                wallet_address="Wallet111",
                trade_mode="real",
            )

        self.assertFalse(buy.call_args.kwargs["auto_confirm"])
        self.assertFalse(sell.call_args.kwargs["auto_confirm"])
        self.assertFalse(components["tiny_auto_confirm"])

    def test_real_fetch_uses_the_fresh_signal_selector(self):
        module = _load_script_module()
        components = {
            "trade_mode": "real",
            "follow_wallets": [{"wallet_address": "Leader111", "total_score": 80}],
            "whitelist_config": {},
            "copy_risk": module.load_copy_risk(),
            "signal_fetcher": object(),
        }

        def collect(wallets, config, profile=None, rate_limit_state=None):
            self.assertEqual(wallets[0]["wallet_address"], "Leader111")
            self.assertIs(profile, components["copy_risk"])
            self.assertEqual(rate_limit_state.name, "gmgn_rate_limit.json")
            return [], []

        def split(observed, profile):
            self.assertEqual(observed, [])
            return [], [{"hold_reason": "stale"}]

        with patch.object(module, "collect_leader_signals", collect), \
             patch.object(module, "split_executable_signals", split):
            signals = module._fetch_signals(components)

        self.assertEqual(signals, [])
        self.assertEqual(components["paper_held_back"], [{"hold_reason": "stale"}])


if __name__ == "__main__":
    unittest.main()
