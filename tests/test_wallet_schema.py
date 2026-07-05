from __future__ import annotations

import pytest

from gmgn_monitor.wallet_schema import (
    VALID_CHAINS,
    VALID_DECISIONS,
    VALID_DIRECTIONS,
    VALID_MEV_MODES,
    VALID_TIERS,
    Wallet,
    WalletScore,
    WalletTrade,
)


# ---------------------------------------------------------------------------
# Wallet helpers
# ---------------------------------------------------------------------------

def _wallet_dict(**overrides: object) -> dict:
    data = {
        "wallet_address": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZR6Y7Q5XqK",
        "chain": "solana",
        "first_seen_at": "2025-01-15T08:30:00Z",
        "last_active_at": "2025-07-03T12:00:00Z",
        "source": "gmgn_mock",
        "fetched_at": "2025-07-03T12:00:00Z",
        "total_trades_7d": 72,
        "total_trades_30d": 280,
        "winning_trades_30d": 192,
        "win_rate_30d": 68.5,
        "avg_investment_usd": 1500.0,
        "avg_profit_usd": 850.0,
        "total_profit_usd": 52000.0,
        "avg_holding_duration_hours": 36.5,
        "stablecoin_balance_usd": 2500.0,
        "portfolio_balance_usd": 15000.0,
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# Wallet tests
# ---------------------------------------------------------------------------

class TestWallet:
    def test_from_dict_valid(self) -> None:
        wallet = Wallet.from_dict(_wallet_dict())
        assert wallet.get("wallet_address") == "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZR6Y7Q5XqK"
        assert wallet.get("chain") == "solana"

    def test_from_dict_missing_required_field(self) -> None:
        data = _wallet_dict()
        del data["wallet_address"]
        with pytest.raises(ValueError, match="missing field: wallet_address"):
            Wallet.from_dict(data)

    def test_from_dict_empty_string(self) -> None:
        with pytest.raises(ValueError, match="wallet_address must be non-empty"):
            Wallet.from_dict(_wallet_dict(wallet_address=""))

    def test_from_dict_invalid_chain(self) -> None:
        with pytest.raises(ValueError, match="chain must be one of"):
            Wallet.from_dict(_wallet_dict(chain="ethereum"))

    def test_from_dict_non_numeric_win_rate(self) -> None:
        with pytest.raises(ValueError, match="win_rate_30d must be numeric"):
            Wallet.from_dict(_wallet_dict(win_rate_30d="high"))

    def test_from_dict_negative_profit(self) -> None:
        with pytest.raises(ValueError, match="total_profit_usd must be non-negative"):
            Wallet.from_dict(_wallet_dict(total_profit_usd=-100))

    def test_from_dict_percent_over_100(self) -> None:
        with pytest.raises(ValueError, match="win_rate_30d must be at most 100"):
            Wallet.from_dict(_wallet_dict(win_rate_30d=101))

    def test_from_dict_non_integer_count(self) -> None:
        with pytest.raises(ValueError, match="total_trades_7d must be an integer"):
            Wallet.from_dict(_wallet_dict(total_trades_7d=10.5))

    def test_from_dict_winning_exceeds_total(self) -> None:
        with pytest.raises(ValueError, match="winning_trades_30d must not exceed total_trades_30d"):
            Wallet.from_dict(_wallet_dict(total_trades_30d=10, winning_trades_30d=15))

    def test_from_dict_last_active_before_first_seen(self) -> None:
        with pytest.raises(ValueError, match="last_active_at must be >= first_seen_at"):
            Wallet.from_dict(
                _wallet_dict(
                    first_seen_at="2025-07-03T12:00:00Z",
                    last_active_at="2025-01-15T08:30:00Z",
                )
            )

    def test_from_dict_invalid_iso_timestamp(self) -> None:
        with pytest.raises(ValueError, match="first_seen_at must be ISO timestamp"):
            Wallet.from_dict(_wallet_dict(first_seen_at="not-a-timestamp"))

    def test_get_existing_field(self) -> None:
        wallet = Wallet.from_dict(_wallet_dict())
        assert wallet.get("total_trades_30d") == 280

    def test_get_missing_field_raises_keyerror(self) -> None:
        wallet = Wallet.from_dict(_wallet_dict())
        with pytest.raises(KeyError):
            wallet.get("nonexistent")

    def test_immutable(self) -> None:
        wallet = Wallet.from_dict(_wallet_dict())
        with pytest.raises(AttributeError):
            wallet.data = {}  # type: ignore[misc]


# ---------------------------------------------------------------------------
# WalletTrade helpers
# ---------------------------------------------------------------------------

def _trade_dict(**overrides: object) -> dict:
    data = {
        "tx_hash": "5Ufabc123",
        "wallet_address": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZR6Y7Q5XqK",
        "chain": "solana",
        "timestamp": "2025-07-01T14:23:00Z",
        "token_address": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "token_symbol": "USDC",
        "direction": "buy",
        "amount_token": 1000.0,
        "amount_sol": 5.5,
        "price_usd": 5.50,
        "slippage_percent": 25.0,
        "fee_sol": 0.005,
        "priority_fee_sol": 0.02,
        "dex": "raydium",
        "program_id": "675kPX9MHTjS2zt1qfr1",
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# WalletTrade tests
# ---------------------------------------------------------------------------

class TestWalletTrade:
    def test_from_dict_valid(self) -> None:
        trade = WalletTrade.from_dict(_trade_dict())
        assert trade.get("direction") == "buy"
        assert trade.get("token_symbol") == "USDC"

    def test_from_dict_missing_field(self) -> None:
        data = _trade_dict()
        del data["tx_hash"]
        with pytest.raises(ValueError, match="missing field: tx_hash"):
            WalletTrade.from_dict(data)

    def test_from_dict_invalid_direction(self) -> None:
        with pytest.raises(ValueError, match="direction must be one of"):
            WalletTrade.from_dict(_trade_dict(direction="swap"))

    def test_from_dict_slippage_over_100(self) -> None:
        with pytest.raises(ValueError, match="slippage_percent must be at most 100"):
            WalletTrade.from_dict(_trade_dict(slippage_percent=150))

    def test_from_dict_invalid_mev_mode(self) -> None:
        with pytest.raises(ValueError, match="mev_protection_mode must be one of"):
            WalletTrade.from_dict(_trade_dict(mev_protection_mode="ultra"))

    def test_from_dict_non_boolean_mev_protected(self) -> None:
        with pytest.raises(ValueError, match="is_mev_protected must be boolean"):
            WalletTrade.from_dict(_trade_dict(is_mev_protected="yes"))

    def test_from_dict_negative_amount(self) -> None:
        with pytest.raises(ValueError, match="amount_sol must be non-negative"):
            WalletTrade.from_dict(_trade_dict(amount_sol=-1.0))

    def test_from_dict_optional_fields_absent(self) -> None:
        # slippage_percent, fee_sol, priority_fee_sol are optional
        data = _trade_dict()
        del data["slippage_percent"]
        del data["fee_sol"]
        del data["priority_fee_sol"]
        trade = WalletTrade.from_dict(data)
        assert trade.get("token_symbol") == "USDC"


# ---------------------------------------------------------------------------
# WalletScore helpers
# ---------------------------------------------------------------------------

def _score_dict(**overrides: object) -> dict:
    data = {
        "wallet_address": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZR6Y7Q5XqK",
        "chain": "solana",
        "score": 82.5,
        "tier": "A",
        "decision": "follow",
        "reasons": ["胜率68.5%超过60%阈值", "夏普比率1.85超过1.5阈值"],
        "metrics": {
            "profitability": 88.0,
            "win_rate": 72.0,
            "risk_control": 75.0,
            "consistency": 80.0,
            "activity": 90.0,
            "stability": 85.0,
        },
        "profitability": 88.0,
        "win_rate": 72.0,
        "risk_control": 75.0,
        "consistency": 80.0,
        "activity": 90.0,
        "stability": 85.0,
        "total_pnl": 125.5,
        "trade_count": 280,
        "avg_hold_time": 36.5,
        "golden_dog_count": 3,
        "robot_score": 12.0,
        "last_updated": "2025-07-03T12:00:00Z",
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# WalletScore tests
# ---------------------------------------------------------------------------

class TestWalletScore:
    def test_from_dict_valid(self) -> None:
        score = WalletScore.from_dict(_score_dict())
        assert score.total_score == 82.5
        assert score.tier == "A"
        assert score.decision == "follow"
        assert score.robot_score == 12.0

    def test_from_dict_missing_required_field(self) -> None:
        data = _score_dict()
        del data["score"]
        with pytest.raises(ValueError, match="missing field: score"):
            WalletScore.from_dict(data)

    def test_from_dict_invalid_score_range(self) -> None:
        with pytest.raises(ValueError, match="score must be between 0 and 100"):
            WalletScore.from_dict(_score_dict(score=101))
        with pytest.raises(ValueError, match="score must be between 0 and 100"):
            WalletScore.from_dict(_score_dict(score=-1))

    def test_from_dict_invalid_tier(self) -> None:
        with pytest.raises(ValueError, match="tier must be one of"):
            WalletScore.from_dict(_score_dict(tier="F"))

    def test_from_dict_invalid_decision(self) -> None:
        with pytest.raises(ValueError, match="decision must be one of"):
            WalletScore.from_dict(_score_dict(decision="unknown"))

    def test_from_dict_invalid_reasons_type(self) -> None:
        with pytest.raises(ValueError, match="reasons must be a list"):
            WalletScore.from_dict(_score_dict(reasons="not a list"))

    def test_from_dict_invalid_reasons_element(self) -> None:
        with pytest.raises(ValueError, match=r"reasons\[0\] must be string"):
            WalletScore.from_dict(_score_dict(reasons=[123, "ok"]))

    def test_from_dict_invalid_metrics_type(self) -> None:
        with pytest.raises(ValueError, match="metrics must be a dict"):
            WalletScore.from_dict(_score_dict(metrics=[1, 2, 3]))

    def test_from_dict_dimension_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="profitability must be between 0 and 100"):
            WalletScore.from_dict(_score_dict(profitability=101))

    def test_from_dict_robot_score_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="robot_score must be between 0 and 100"):
            WalletScore.from_dict(_score_dict(robot_score=101))

    def test_dimension_score_from_metrics(self) -> None:
        score = WalletScore.from_dict(_score_dict())
        assert score.dimension_score("profitability") == 88.0
        assert score.dimension_score("win_rate") == 72.0

    def test_dimension_score_from_top_level(self) -> None:
        data = _score_dict()
        del data["metrics"]
        score = WalletScore.from_dict(data)
        assert score.dimension_score("profitability") == 88.0

    def test_dimension_score_missing(self) -> None:
        score = WalletScore.from_dict(_score_dict())
        assert score.dimension_score("nonexistent") is None

    def test_property_defaults(self) -> None:
        score = WalletScore.from_dict(_score_dict())
        assert score.total_score == 82.5
        assert score.tier == "A"
        assert score.decision == "follow"

    def test_immutable(self) -> None:
        score = WalletScore.from_dict(_score_dict())
        with pytest.raises(AttributeError):
            score.data = {}  # type: ignore[misc]

    def test_score_not_numeric(self) -> None:
        with pytest.raises(ValueError, match="score must be numeric"):
            WalletScore.from_dict(_score_dict(score="high"))

    def test_score_infinite(self) -> None:
        with pytest.raises(ValueError, match="score must be finite"):
            WalletScore.from_dict(_score_dict(score=float("inf")))

    def test_robot_score_not_numeric(self) -> None:
        with pytest.raises(ValueError, match="robot_score must be numeric"):
            WalletScore.from_dict(_score_dict(robot_score="low"))

    def test_robot_score_boolean(self) -> None:
        with pytest.raises(ValueError, match="robot_score must be numeric"):
            WalletScore.from_dict(_score_dict(robot_score=True))
