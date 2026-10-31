from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gmgn_monitor.copy_trade_guards import (
    CopyTradeContext,
    CopyTradeGuardConfig,
    CopyTradeGuards,
    demote_leader_in_whitelist,
    load_copy_trade_guard_config,
)


class CopyTradeGuardsTests(unittest.TestCase):
    def test_chase_premium_blocks_above_limit(self) -> None:
        guards = CopyTradeGuards(CopyTradeGuardConfig(max_chase_percent=15.0))
        decision = guards.evaluate_buy(
            "Wallet1",
            CopyTradeContext(
                leader_entry_price=0.0010,
                expected_entry_price=0.0016,
                amount_sol=0.01,
            ),
        )
        self.assertFalse(decision.allow)
        self.assertEqual(decision.reason, "chase_premium")

    def test_chase_premium_allows_within_limit(self) -> None:
        guards = CopyTradeGuards(CopyTradeGuardConfig(max_chase_percent=15.0))
        decision = guards.evaluate_buy(
            "Wallet1",
            CopyTradeContext(
                leader_entry_price=0.0010,
                expected_entry_price=0.0011,
                amount_sol=0.01,
            ),
        )
        self.assertTrue(decision.allow)

    def test_stale_signal_blocked(self) -> None:
        now = datetime(2026, 10, 31, 6, 0, tzinfo=timezone.utc)
        guards = CopyTradeGuards(CopyTradeGuardConfig(max_signal_age_seconds=20.0))
        decision = guards.evaluate_buy(
            "Wallet1",
            CopyTradeContext(
                leader_traded_at=now - timedelta(seconds=45),
                amount_sol=0.01,
            ),
            now=now,
        )
        self.assertFalse(decision.allow)
        self.assertEqual(decision.reason, "signal_stale")

    def test_security_hard_rejects(self) -> None:
        guards = CopyTradeGuards(CopyTradeGuardConfig())
        honeypot = guards.evaluate_buy(
            "Wallet1",
            CopyTradeContext(amount_sol=0.01, honeypot_risk=True),
        )
        self.assertEqual(honeypot.reason, "honeypot")
        unlocked = guards.evaluate_buy(
            "Wallet1",
            CopyTradeContext(amount_sol=0.01, lp_burned_or_locked=False),
        )
        self.assertEqual(unlocked.reason, "lp_unlocked")

    def test_wallet_daily_exposure_cap(self) -> None:
        guards = CopyTradeGuards(
            CopyTradeGuardConfig(max_wallet_daily_exposure_sol=0.01, max_single_trade_sol=0.01)
        )
        first = guards.evaluate_buy("Wallet1", CopyTradeContext(amount_sol=0.01))
        self.assertTrue(first.allow)
        guards.reserve_exposure("Wallet1", 0.01)
        second = guards.evaluate_buy("Wallet1", CopyTradeContext(amount_sol=0.01))
        self.assertFalse(second.allow)
        self.assertEqual(second.reason, "wallet_daily_exposure_cap")

    def test_consecutive_losses_queue_demotion(self) -> None:
        guards = CopyTradeGuards(CopyTradeGuardConfig(consecutive_loss_limit=3))
        self.assertFalse(guards.record_copy_outcome("Wallet1", -0.001))
        self.assertFalse(guards.record_copy_outcome("Wallet1", -0.001))
        self.assertTrue(guards.record_copy_outcome("Wallet1", -0.001))
        pending = guards.drain_demotions()
        self.assertEqual(
            pending,
            [
                {
                    "wallet_address": "Wallet1",
                    "reason": "consecutive copy losses >= 3",
                }
            ],
        )
        blocked = guards.evaluate_buy("Wallet1", CopyTradeContext(amount_sol=0.01))
        self.assertEqual(blocked.reason, "leader_demoted_consecutive_losses")

    def test_demote_leader_in_whitelist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wallet_whitelist.json"
            path.write_text(
                json.dumps(
                    {
                        "wallets": [
                            {
                                "wallet_address": "Leader111",
                                "mode": "follow",
                                "enabled": True,
                                "copy_weight": 0.2,
                                "notes": "active",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            self.assertTrue(demote_leader_in_whitelist(path, "Leader111", reason="3 losses"))
            updated = json.loads(path.read_text(encoding="utf-8"))
            wallet = updated["wallets"][0]
            self.assertFalse(wallet["enabled"])
            self.assertEqual(wallet["mode"], "observe")
            self.assertEqual(wallet["copy_weight"], 0.0)
            self.assertIn("auto-demote", wallet["notes"])

    def test_load_config_from_repo(self) -> None:
        config = load_copy_trade_guard_config(Path("config/copy_trade_guards.json"))
        self.assertEqual(config.max_chase_percent, 15.0)
        self.assertEqual(config.max_signal_age_seconds, 20.0)
        self.assertEqual(config.consecutive_loss_limit, 3)


if __name__ == "__main__":
    unittest.main()
