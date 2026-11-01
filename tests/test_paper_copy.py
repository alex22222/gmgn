from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from gmgn_monitor.paper_copy import (
    PaperBuyExecutor,
    PaperSellExecutor,
    collect_leader_signals,
    copy_trading_enabled,
    paper_amount_sol,
    parse_activity_payload,
    resolve_trade_mode,
    select_leader_signals,
)
from gmgn_monitor.portfolio_tracker import PortfolioTracker
from gmgn_monitor.real_trade_executor import RealTradeExecutor
from gmgn_monitor.sell_executor import SellSignal
from scripts.run_auto_copy_trading import _init_components


NOW = datetime(2026, 11, 1, 14, 0, tzinfo=timezone.utc)


def _wallet() -> dict:
    return {
        "wallet_address": "Leader111",
        "label": "leader_pool_9",
        "total_score": 88.0,
        "risk_limits": {
            "max_single_trade_sol": 0.01,
            "slippage_percent": 2.0,
            "stop_loss_percent": -40.0,
            "take_profit_steps": [
                {"price_change_percent": 100.0, "sell_percent": 50.0},
            ],
        },
    }


def _activity(event_type: str, timestamp: int, quote: float, symbol: str = "DOGE") -> dict:
    return {
        "event_type": event_type,
        "timestamp": timestamp,
        "quote_amount": quote,
        "cost_usd": quote * 100,
        "tx_hash": f"tx-{event_type}-{timestamp}",
        "token": {"address": "Token111111", "symbol": symbol},
    }


class PaperCopyTests(unittest.TestCase):
    def test_parse_activity_payload_reads_activities(self):
        payload = {"activities": [_activity("buy", 1790000000, 0.05)], "next": "cursor"}
        self.assertEqual(len(parse_activity_payload(payload)), 1)

    def test_paper_amount_caps_sol_and_ignores_usd_sized_quotes(self):
        self.assertEqual(paper_amount_sol({"quote_amount": 0.093}, 0.01), 0.01)
        self.assertEqual(paper_amount_sol({"quote_amount": 0.004}, 0.01), 0.004)
        self.assertEqual(paper_amount_sol({"quote_amount": 4587.0}, 0.01), 0.01)

    def test_select_leader_signals_keeps_newest_buy_and_sell_inside_window(self):
        latest = int(NOW.timestamp()) - 3600
        older = latest - 86400
        stale = int((NOW - timedelta(days=40)).timestamp())
        activities = [
            _activity("buy", older, 0.2, "OLD"),
            _activity("buy", latest, 0.05, "NEW"),
            _activity("sell", latest - 10, 0.02, "NEW"),
            _activity("buy", stale, 1.0, "STALE"),
            {"event_type": "transfer", "timestamp": latest, "token": {"address": "Token111111"}},
        ]

        selected = select_leader_signals(
            activities,
            _wallet(),
            now=NOW,
            lookback=timedelta(days=30),
        )

        kinds = sorted(item.event_type for item in selected)
        self.assertEqual(kinds, ["buy", "sell"])
        buy = next(item for item in selected if item.event_type == "buy")
        self.assertEqual(buy.symbol, "NEW")
        self.assertEqual(buy.signal.signal_type, "NEW_POSITION")
        self.assertEqual(buy.signal.recommended_amount_sol, 0.01)
        self.assertEqual(buy.signal.wallet_address, "Leader111")
        self.assertEqual(buy.tx_hash, f"tx-buy-{latest}")

    def test_resolve_trade_mode_keeps_paper_config_off_the_chain(self):
        paper = {"trade_mode": "paper", "global_settings": {"copy_trading_enabled": True}}
        self.assertEqual(resolve_trade_mode(paper), "paper")
        self.assertEqual(resolve_trade_mode({"trade_mode": "dryrun"}), "paper")
        self.assertTrue(copy_trading_enabled(paper))
        with self.assertRaises(ValueError):
            resolve_trade_mode(paper, real=True)
        self.assertEqual(resolve_trade_mode({"trade_mode": "real"}, real=True), "real")

    def test_paper_buy_executor_confirms_without_building_a_live_executor(self):
        executor = PaperBuyExecutor()
        selected = select_leader_signals(
            [_activity("buy", int(NOW.timestamp()), 0.05)],
            _wallet(),
            now=NOW,
            lookback=timedelta(days=1),
        )
        result = executor.execute_trade(selected[0].signal)

        self.assertTrue(result.success)
        self.assertIsNotNone(result.tx_hash)
        self.assertTrue(str(result.tx_hash).startswith("paper-"))
        self.assertIsNotNone(result.trade_execution)
        assert result.trade_execution is not None
        self.assertTrue(result.trade_execution.dry_run)
        self.assertFalse(hasattr(executor, "_client"))

    def test_paper_sell_executor_closes_local_position_only(self):
        portfolio = PortfolioTracker(initial_balance_sol=10.0)
        portfolio.open_position("Token111111", entry_price_sol=1.0, quantity=0.01)
        executor = PaperSellExecutor(portfolio)

        closed = executor.execute_sell(SellSignal(
            signal_id="sell-1",
            token_address="Token111111",
            sell_percent=100.0,
            trigger_type="COPY_EXIT",
        ))
        missing = executor.execute_sell(SellSignal(
            signal_id="sell-2",
            token_address="Token111111",
            sell_percent=100.0,
            trigger_type="COPY_EXIT",
        ))

        self.assertTrue(closed.success)
        self.assertIsNotNone(closed.tx_hash)
        self.assertTrue(str(closed.tx_hash).startswith("paper-sell-"))
        self.assertIsNone(portfolio.get_position("Token111111"))
        self.assertFalse(missing.success)
        self.assertEqual(missing.error_message, "Zero token balance")

    def test_paper_init_does_not_construct_real_trade_executor(self):
        config = {
            "trade_mode": "paper",
            "global_settings": {"copy_trading_enabled": True},
            "wallets": [{
                "wallet_address": "Leader111",
                "mode": "follow",
                "enabled": True,
                "total_score": 80,
                "risk_limits": {"max_single_trade_sol": 0.01, "stop_loss_percent": -40},
            }],
        }
        components = _init_components(config, "test-key", "", trade_mode="paper")

        self.assertIsInstance(components["buy_executor"], PaperBuyExecutor)
        self.assertNotIsInstance(components["buy_executor"], RealTradeExecutor)
        self.assertFalse(components["liquidate_removed_leaders"])
        self.assertIsNone(components["gmgn_client"])

    def test_collect_leader_signals_uses_loader_and_records_fetch_notes(self):
        calls: list[str] = []

        def loader(address: str):
            calls.append(address)
            return [_activity("buy", int(NOW.timestamp()) - 60, 0.02)]

        observed, notes = collect_leader_signals(
            [_wallet()],
            {"global_settings": {"paper_lookback_days": 7}},
            now=NOW,
            sleeper=lambda _seconds: None,
            activity_loader=loader,
        )

        self.assertEqual(calls, ["Leader111"])
        self.assertEqual(notes[0]["status"], "ok")
        self.assertEqual(notes[0]["selected"], 1)
        self.assertIn("newest_event_time", notes[0])
        self.assertEqual(observed[0].signal.target_token, "Token111111")


if __name__ == "__main__":
    unittest.main()
