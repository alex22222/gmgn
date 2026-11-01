from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gmgn_monitor.copy_risk import CopyRiskProfile, load_copy_risk
from gmgn_monitor.css_engine import (
    CSSDecision,
    CSSEngine,
    AccountState,
    MarketCondition,
    TimeMomentum,
    TokenRiskScore,
)
from gmgn_monitor.execution_loop import ExecutionLoopEngine
from gmgn_monitor.order_manager import OrderManager
from gmgn_monitor.risk_manager import RiskManager
from gmgn_monitor.signal_preprocessor import SignalPreprocessor
from gmgn_monitor.paper_copy import (
    ObservedLeaderSignal,
    PaperBuyExecutor,
    PaperSellExecutor,
    collect_leader_signals,
    copy_trading_enabled,
    paper_amount_sol,
    parse_activity_payload,
    resolve_trade_mode,
    select_leader_signals,
    split_executable_signals,
)
from gmgn_monitor.trade_signal import TradeSignal
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
        self.assertEqual(components["loop"].css_engine.pass_score, 60.0)
        self.assertEqual(components["loop"].css_engine.watch_score, 45.0)

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

    def test_repo_copy_risk_matches_tiny_real_caps(self):
        profile = load_copy_risk()
        self.assertEqual(profile.max_single_trade_sol, 0.01)
        self.assertEqual(profile.max_daily_loss_sol, 0.03)
        self.assertEqual(profile.max_positions, 3)
        self.assertEqual(profile.max_slippage_percent, 5.0)
        self.assertEqual(profile.stop_loss_percent, -40.0)
        self.assertEqual(profile.min_leader_score, 65.0)
        self.assertEqual(profile.max_signal_age_minutes, 30)
        self.assertEqual(profile.max_single_position_percent, 2.0)
        self.assertEqual(profile.css_pass_score, 60.0)
        self.assertEqual(profile.css_watch_score, 45.0)

    def test_split_holds_stale_signals_and_extra_buys(self):
        profile = CopyRiskProfile(max_signal_age_minutes=30, max_daily_trades=1)
        fresh = _observed(10, "buy", "TokenFresh")
        extra = _observed(5, "buy", "TokenExtra")
        stale = _observed(120, "buy", "TokenStale")

        executable, held = split_executable_signals(
            [fresh, extra, stale],
            profile,
            now=NOW,
        )

        self.assertEqual([item.signal.target_token for item in executable], ["TokenFresh"])
        self.assertEqual(executable[0].signal.received_at, NOW.replace(tzinfo=None))
        reasons = {item["token"]: item["hold_reason"] for item in held}
        self.assertEqual(reasons["TokenExtra"], "max_daily_trades")
        self.assertEqual(reasons["TokenStale"], "stale")

    def test_paper_buy_blocks_size_and_daily_loss(self):
        profile = CopyRiskProfile()
        selected = select_leader_signals(
            [_activity("buy", int(NOW.timestamp()), 0.05)],
            _wallet(),
            now=NOW,
            lookback=timedelta(days=1),
        )
        oversized = replace(selected[0].signal, recommended_amount_sol=0.02)
        executor = PaperBuyExecutor(copy_risk=profile)
        blocked = executor.execute_trade(oversized)
        self.assertFalse(blocked.success)
        self.assertEqual(blocked.error_message, "exceeds max_single_trade_sol")

        portfolio = PortfolioTracker(initial_balance_sol=10.0)
        portfolio.open_position("OldToken", entry_price_sol=1.0, quantity=0.05)
        portfolio.close_position("OldToken", exit_price_sol=0.0)
        lost = PaperBuyExecutor(portfolio=portfolio, copy_risk=profile)
        loss_block = lost.execute_trade(selected[0].signal)
        self.assertFalse(loss_block.success)
        self.assertEqual(loss_block.error_message, "daily loss limit")

    def test_below_score_leader_is_not_fetched(self):
        calls: list[str] = []

        def loader(address: str):
            calls.append(address)
            return []

        wallet = _wallet()
        wallet["total_score"] = 40
        observed, notes = collect_leader_signals(
            [wallet],
            {},
            now=NOW,
            sleeper=lambda _seconds: None,
            activity_loader=loader,
            profile=CopyRiskProfile(min_leader_score=65),
        )
        self.assertEqual(calls, [])
        self.assertEqual(observed, [])
        self.assertEqual(notes[0]["status"], "below_score")

    def test_copy_order_line_fills_a_fresh_65_leader_that_global_css_watches(self):
        signal = TradeSignal(
            signal_id="paper-fresh-65",
            wallet_address="Leader111",
            target_token="TokenFresh111",
            signal_type="NEW_POSITION",
            urgency_score=65,
            confidence_score=70,
            quality_score=65,
            recommended_amount_sol=0.01,
            max_slippage_percent=2.0,
            received_at=datetime.utcnow(),
        )
        scores = {"Leader111": 65.0}
        profile = load_copy_risk()
        neutral = _neutral_css_inputs()
        global_result = CSSEngine().evaluate(signal=signal, wallet_score=65.0, **neutral)
        copy_engine = CSSEngine(pass_score=profile.css_pass_score, watch_score=profile.css_watch_score)
        copy_result = copy_engine.evaluate(signal=signal, wallet_score=65.0, **neutral)
        self.assertLess(global_result.css_score, 70.0)
        self.assertGreaterEqual(global_result.css_score, 60.0)
        self.assertEqual(global_result.decision, CSSDecision.WATCH)
        self.assertEqual(copy_result.decision, CSSDecision.PASS)
        self.assertEqual(copy_result.css_score, global_result.css_score)

        watched = _run_copy_cycle(signal, scores, CSSEngine(), profile)
        ordered = _run_copy_cycle(signal, scores, copy_engine, profile)
        self.assertEqual(watched["css_pass_count"], 0)
        self.assertEqual(watched["orders_created"], [])
        self.assertEqual(ordered["css_pass_count"], 1)
        self.assertEqual(len(ordered["orders_created"]), 1)
        self.assertEqual(ordered["orders_created"][0]["amount_sol"], 0.01)

    def test_copy_risk_rejects_an_order_line_below_the_reject_floor(self):
        raw = json.loads(Path("config/copy_risk.json").read_text(encoding="utf-8"))
        raw["gates"]["css_pass_score"] = 40
        raw["gates"]["css_watch_score"] = 30
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "copy_risk.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_copy_risk(path)
        raw["gates"]["css_pass_score"] = 55
        raw["gates"]["css_watch_score"] = 60
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "copy_risk.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_copy_risk(path)


def _neutral_css_inputs() -> dict:
    return {
        "token_risk": TokenRiskScore(
            liquidity_score=50.0,
            contract_safe=True,
            market_cap_usd=1_000_000.0,
            holder_count=1_000,
        ),
        "market": MarketCondition(btc_trend_24h=0.0, overall_sentiment=50.0, fear_greed_index=50.0),
        "account": AccountState(
            balance_sol=10.0,
            open_positions_count=0,
            daily_pnl_sol=0.0,
            daily_loss_limit_sol=1.0,
            max_positions=3,
        ),
        "momentum": TimeMomentum(signal_age_seconds=0.0, chain_activity_score=50.0, volume_surge_1h=0.0),
    }


def _run_copy_cycle(signal: TradeSignal, scores: dict[str, float], engine: CSSEngine, profile: CopyRiskProfile) -> dict:
    loop = ExecutionLoopEngine(
        css_engine=engine,
        preprocessor=SignalPreprocessor(
            min_confidence=profile.min_signal_quality,
            min_wallet_score=profile.min_leader_score,
        ),
        risk_manager=RiskManager(profile.to_risk_limits()),
        order_manager=OrderManager(),
        portfolio_tracker=PortfolioTracker(initial_balance_sol=10.0),
    )
    return loop.run_cycle([signal], scores)


def _observed(minutes_ago: int, event_type: str, token: str) -> ObservedLeaderSignal:
    event_time = NOW - timedelta(minutes=minutes_ago)
    signal_type = "EXIT" if event_type == "sell" else "NEW_POSITION"
    signal = TradeSignal(
        signal_id=f"paper-{token}",
        wallet_address="Leader111",
        target_token=token,
        signal_type=signal_type,
        urgency_score=80,
        confidence_score=70,
        quality_score=80,
        recommended_amount_sol=0.01,
        max_slippage_percent=2.0,
        received_at=event_time.replace(tzinfo=None),
    )
    return ObservedLeaderSignal(
        signal=signal,
        label="leader",
        symbol=token,
        event_type=event_type,
        event_time=event_time,
        age_hours=minutes_ago / 60.0,
        tx_hash=f"tx-{token}",
        leader_quote_amount=0.01,
        leader_cost_usd=1.0,
    )


if __name__ == "__main__":
    unittest.main()
