from __future__ import annotations

import unittest

from pathlib import Path
import json
import tempfile

from gmgn_monitor.copy_leader_fit import assess_copy_fit, build_copy_review, load_scored_leaders, split_arbitrage


def _fill(kind: str, token: str, timestamp: int, amount: float, sol: float, fee: float = 0.0) -> dict:
    return {
        "event_type": kind,
        "timestamp": timestamp,
        "token": {"address": token, "symbol": "TOK"},
        "token_amount": amount,
        "quote_amount": sol,
        "gas_native": fee,
    }


def _slow_activities(count: int = 8) -> list[dict]:
    rows: list[dict] = []
    for index in range(count):
        start = 1_700_000_000 + index * 10_000
        token = f"Token{index}"
        rows.append(_fill("buy", token, start, 100, 1.0, 0.01))
        rows.append(_fill("sell", token, start + 20 * 60, 100, 1.2, 0.001))
    return rows


class CopyLeaderFitTests(unittest.TestCase):
    def test_slow_positive_leader_is_pending_confirmation(self) -> None:
        result = assess_copy_fit(
            _slow_activities(),
            score=70.2,
            realized_profit=1200,
            tags=["smart_degen"],
        )

        self.assertEqual(result["decision"], "pending_confirmation")
        self.assertEqual(result["reasons"], [])
        self.assertEqual(result["closed_round_trips"], 8)
        self.assertGreaterEqual(result["median_hold_seconds"], 15 * 60)
        self.assertEqual(result["fast_close_count"], 0)

    def test_fast_round_trips_are_rejected(self) -> None:
        rows: list[dict] = []
        for index in range(8):
            start = 1_700_000_000 + index * 100
            token = f"Fast{index}"
            rows.append(_fill("buy", token, start, 50, 3))
            rows.append(_fill("sell", token, start + 3, 50, 3.4))

        result = assess_copy_fit(rows, score=75, realized_profit=500, tags=[])

        self.assertEqual(result["decision"], "rejected")
        self.assertTrue(any("90s" in reason for reason in result["reasons"]))
        self.assertIn("8/8 笔在 90 秒内平仓", result["reasons_zh"])

    def test_score_at_review_floor_is_rejected(self) -> None:
        result = assess_copy_fit(_slow_activities(), score=60, realized_profit=10, tags=[])

        self.assertEqual(result["decision"], "rejected")
        self.assertTrue(any("score" in reason for reason in result["reasons"]))

    def test_wash_trader_tag_is_rejected(self) -> None:
        result = assess_copy_fit(
            _slow_activities(),
            score=80,
            realized_profit=10,
            tags=["wash_trader", "smart_degen"],
        )

        self.assertEqual(result["decision"], "rejected")
        self.assertEqual(result["blocked_tags"], ["wash_trader"])

    def test_non_positive_profit_is_rejected(self) -> None:
        result = assess_copy_fit(_slow_activities(), score=80, realized_profit=0, tags=[])

        self.assertEqual(result["decision"], "rejected")
        self.assertTrue(any("profit" in reason for reason in result["reasons"]))

    def test_short_sample_is_not_pending(self) -> None:
        result = assess_copy_fit(_slow_activities(3), score=80, realized_profit=10, tags=[])

        self.assertEqual(result["decision"], "rejected")
        self.assertTrue(any("closed round trips" in reason for reason in result["reasons"]))

    def test_hard_rejected_wallet_cannot_become_pending(self) -> None:
        review = build_copy_review(
            [{
                "wallet_address": "HardWallet",
                "total_score": 80,
                "hard_rejected": True,
                "stats": {"realized_profit": 10, "winrate": 0.8},
            }],
            {"HardWallet": _slow_activities()},
        )

        self.assertEqual(review["pending"], [])
        self.assertEqual(review["rejected_count"], 1)
        self.assertTrue(any("hard-rejected" in reason for reason in review["rejected"][0]["copy_fit"]["reasons"]))
        self.assertFalse(review["rules"]["auto_follow"])

    def test_load_scored_leaders_keeps_scores_above_sixty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            data = root / "data"
            data.mkdir()
            (data / "whitelist_wallets.json").write_text(json.dumps([
                {"wallet_address": "Keep", "total_score": 70.2},
                {"wallet_address": "Floor", "total_score": 60},
            ]), encoding="utf-8")
            (data / "watchlist_wallets.json").write_text(json.dumps([
                {"wallet_address": "Keep", "total_score": 61},
            ]), encoding="utf-8")
            (data / "blacklist_wallets.json").write_text("[]", encoding="utf-8")

            loaded = load_scored_leaders(root)

        self.assertEqual([item["wallet_address"] for item in loaded], ["Keep"])
        self.assertEqual(loaded[0]["total_score"], 70.2)

    def test_arbitrage_wallet_is_excluded_from_confirmation(self) -> None:
        review = build_copy_review(
            [
                {
                    "wallet_address": "SlowWallet",
                    "total_score": 71,
                    "stats": {"realized_profit": 100, "winrate": 0.7},
                },
                {
                    "wallet_address": "ArbWallet",
                    "total_score": 80,
                    "stats": {"realized_profit": 5000, "winrate": 0.8},
                },
            ],
            {
                "SlowWallet": _slow_activities(),
                "ArbWallet": _slow_activities(),
            },
            tags_by_address={"ArbWallet": ["arbitrager"]},
        )

        self.assertEqual([item["wallet_address"] for item in review["pending"]], ["SlowWallet"])
        self.assertEqual(review["rejected"], [])
        self.assertEqual(review["excluded"][0]["status"], "excluded_arbitrage")
        self.assertEqual(review["excluded"][0]["confirmation"], "not_offered")
        self.assertFalse(review["excluded"][0]["follow_enabled"])
        self.assertIn("套利地址，已排除", review["excluded"][0]["copy_fit"]["reasons_zh"])
