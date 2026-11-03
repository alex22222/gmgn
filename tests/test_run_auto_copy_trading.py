from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gmgn_monitor.portfolio_tracker import PortfolioTracker
from gmgn_monitor.sell_trigger import SellTrigger
from gmgn_monitor.trade_signal import TradeSignal


def _load_script_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_auto_copy_trading.py"
    spec = importlib.util.spec_from_file_location("run_auto_copy_trading", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_zero_balance_sell_cleans_position_and_sets_cooldown(tmp_path):
    module = _load_script_module()
    portfolio = PortfolioTracker(initial_balance_sol=10.0)
    portfolio.open_position("Token111", entry_price_sol=1.0, quantity=1.0)
    sell_trigger = SellTrigger(
        triggered_tp_file=str(tmp_path / "triggered_tp.json"),
        signal_cache_file=str(tmp_path / "signal_cache.json"),
    )
    components = {
        "portfolio": portfolio,
        "sell_trigger": sell_trigger,
        "sell_cooldowns": {},
    }

    module._handle_sell_result_cleanup(
        components,
        "Token111",
        success=False,
        error_message="Zero token balance",
        sell_percent=100.0,
    )

    assert portfolio.get_position("Token111") is None
    assert module._sell_cooldown_reason(components, "Token111") == "zero_balance"


def test_copy_sell_seen_deduplicates_same_wallet_token_type():
    module = _load_script_module()
    components = {"copy_sell_seen": {}}
    first = TradeSignal(
        signal_id="sig-1",
        wallet_address="Wallet111",
        target_token="Token111",
        signal_type="EXIT",
        urgency_score=70,
        confidence_score=70,
        quality_score=70,
        recommended_amount_sol=0.01,
    )
    second = TradeSignal(
        signal_id="sig-2",
        wallet_address="Wallet111",
        target_token="Token111",
        signal_type="EXIT",
        urgency_score=70,
        confidence_score=70,
        quality_score=70,
        recommended_amount_sol=0.01,
    )

    assert module._copy_sell_seen(components, first) is False
    assert module._copy_sell_seen(components, second) is True


def test_add_skip_aggregates_reasons():
    module = _load_script_module()
    summary = {}

    module._add_skip(summary, "zero_balance")
    module._add_skip(summary, "zero_balance")
    module._add_skip(summary, "duplicate_signal")

    assert summary == {
        "zero_balance": 2,
        "duplicate_signal": 1,
    }


def test_sync_buy_executor_portfolio_drops_stale_internal_positions():
    module = _load_script_module()
    shared_portfolio = PortfolioTracker(initial_balance_sol=10.0)
    stale_portfolio = PortfolioTracker(initial_balance_sol=10.0)
    stale_portfolio.open_position("OldToken1", entry_price_sol=1.0, quantity=1.0)
    stale_portfolio.open_position("OldToken2", entry_price_sol=1.0, quantity=1.0)
    stale_portfolio.open_position("OldToken3", entry_price_sol=1.0, quantity=1.0)

    class BuyExecutor:
        _portfolio = stale_portfolio

    components = {
        "portfolio": shared_portfolio,
        "buy_executor": BuyExecutor(),
    }

    module._sync_buy_executor_portfolio(components)

    assert components["buy_executor"]._portfolio is not shared_portfolio
    assert components["buy_executor"]._portfolio.list_positions() == []
    assert shared_portfolio.list_positions() == []


def test_sync_buy_executor_portfolio_preserves_shared_positions():
    module = _load_script_module()
    shared_portfolio = PortfolioTracker(initial_balance_sol=10.0)
    shared_portfolio.open_position("CurrentToken", entry_price_sol=1.0, quantity=2.0)
    shared_portfolio.update_price("CurrentToken", 1.5)

    class BuyExecutor:
        _portfolio = PortfolioTracker(initial_balance_sol=10.0)

    components = {
        "portfolio": shared_portfolio,
        "buy_executor": BuyExecutor(),
    }

    module._sync_buy_executor_portfolio(components)

    cloned_position = components["buy_executor"]._portfolio.get_position("CurrentToken")
    assert cloned_position is not None
    assert cloned_position.quantity == 2.0
    assert cloned_position.current_price_sol == 1.5
    assert components["buy_executor"]._portfolio.get_snapshot().total_value_sol == 11.0


def test_refresh_follow_config_reloads_current_whitelist(tmp_path):
    module = _load_script_module()
    whitelist_path = tmp_path / "wallet_whitelist.json"
    whitelist_path.write_text(
        """
        {
          "wallets": [
            {"wallet_address": "NewFollow111", "mode": "follow", "enabled": true, "total_score": 81},
            {"wallet_address": "OldFollow111", "mode": "observe", "enabled": true, "total_score": 70},
            {"wallet_address": "Paused111", "mode": "follow", "enabled": false, "total_score": 90}
          ]
        }
        """,
        encoding="utf-8",
    )

    class Fetcher:
        wallet_scores = {"OldFollow111": 70.0}

    components = {
        "whitelist_path": whitelist_path,
        "follow_wallets": [{"wallet_address": "OldFollow111", "mode": "follow"}],
        "wallet_scores": {"OldFollow111": 70.0},
        "signal_fetcher": Fetcher(),
    }

    follow_wallets = module._refresh_follow_config(components)

    assert [wallet["wallet_address"] for wallet in follow_wallets] == ["NewFollow111"]
    assert components["wallet_scores"] == {"NewFollow111": 81}
    assert components["signal_fetcher"].wallet_scores == {"NewFollow111": 81}


def test_refresh_follow_config_liquidates_removed_follow_leader(tmp_path):
    module = _load_script_module()
    whitelist_path = tmp_path / "wallet_whitelist.json"
    whitelist_path.write_text(
        """
        {
          "wallets": [
            {"wallet_address": "NewFollow111", "mode": "follow", "enabled": true, "total_score": 81}
          ]
        }
        """,
        encoding="utf-8",
    )
    components = {
        "whitelist_path": whitelist_path,
        "follow_wallets": [{"wallet_address": "RemovedLeader111", "mode": "follow"}],
        "wallet_scores": {"RemovedLeader111": 70.0},
        "liquidate_removed_leaders": True,
    }

    with patch("gmgn_monitor.dashboard._liquidate_leader_positions", return_value={
        "matched_positions": 2,
        "results": [],
    }) as liquidate:
        module._refresh_follow_config(components)

    liquidate.assert_called_once()
    assert liquidate.call_args.args[1] == "RemovedLeader111"


def test_filter_current_follow_signals_drops_removed_leader():
    module = _load_script_module()
    components = {
        "follow_wallets": [{"wallet_address": "CurrentLeader111", "mode": "follow"}],
    }
    current_signal = TradeSignal(
        signal_id="sig-current",
        wallet_address="CurrentLeader111",
        target_token="Token111",
        signal_type="NEW_POSITION",
        urgency_score=70,
        confidence_score=70,
        quality_score=70,
        recommended_amount_sol=0.01,
    )
    stale_signal = TradeSignal(
        signal_id="sig-stale",
        wallet_address="RemovedLeader111",
        target_token="Token222",
        signal_type="NEW_POSITION",
        urgency_score=70,
        confidence_score=70,
        quality_score=70,
        recommended_amount_sol=0.01,
    )

    assert module._filter_current_follow_signals(
        components,
        [current_signal, stale_signal],
    ) == [current_signal]


class PaymentWalletTests(unittest.TestCase):
    def test_reads_wallet_json_when_env_is_unset(self) -> None:
        module = _load_script_module()
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "config").mkdir()
            (root / "config" / "wallet.json").write_text(
                json.dumps({"gmgn_wallet_address": "BM76JAzFzCEUbPCgBzpTTTiAXkxYFttNVLQDjH4iEqc6"}),
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                address = module._configured_payment_wallet(root)
                overridden = module._configured_payment_wallet(root, explicit="CliWallet111")
            with patch.dict(os.environ, {"GMGN_WALLET_ADDRESS": "EnvWallet111"}, clear=True):
                from_env = module._configured_payment_wallet(root)

        self.assertEqual(address, "BM76JAzFzCEUbPCgBzpTTTiAXkxYFttNVLQDjH4iEqc6")
        self.assertEqual(overridden, "CliWallet111")
        self.assertEqual(from_env, "EnvWallet111")
