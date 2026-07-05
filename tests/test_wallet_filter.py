from __future__ import annotations

import json

import pytest

from gmgn_monitor.wallet_filter import (
    FilterThresholds,
    filter_wallet,
    _hard_reject_reasons,
    _soft_penalties,
    FilterConfig,
    load_filter_config,
)
from gmgn_monitor.wallet_robot_detector import WalletFeatures


def _features(**overrides) -> WalletFeatures:
    """Build a WalletFeatures with healthy defaults, overridden by kwargs."""
    base = {
        "wallet_address": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZR6Y7Q5XqK",
        "trades_7d": 50,
        "trades_30d": 200,
        "win_rate_percent": 65.0,
        "total_profit_usd": 50000.0,
        "avg_holding_hours": 36.0,
        "total_trades": 300,
        "single_token_concentration_percent": 30.0,
        "self_transfer_ratio_percent": 5.0,
        "inactive_days": 3,
        "is_mev_attacker": False,
        "is_dev_associated": False,
        "trade_intervals_seconds": [3600.0 + i * 300 for i in range(50)],
        "trade_hours_of_day": [8, 9, 10, 11, 12, 13, 14, 15, 16] * 10,
        "fees_sol_list": [0.005 + i * 0.001 for i in range(50)],
        "wallet_age_days": 90,
        "diversification_index": 0.6,
        "volatility_30d": 0.3,
        "turbo_slippage_usage_percent": 30.0,
        "mev_usage_percent": 20.0,
        "pump_fun_interaction_percent": 50.0,
        "large_gambler_ratio_percent": 30.0,
        "stop_loss_trigger_rate_percent": 50.0,
    }
    base.update(overrides)
    return WalletFeatures.from_dict(base)


class TestHardReject:
    """Tests for _hard_reject_reasons covering all 10+ hard rules."""

    def test_healthy_wallet_no_hard_reject(self):
        f = _features()
        t = FilterThresholds()
        reasons = _hard_reject_reasons(f, t, 0.0)
        assert reasons == []

    def test_h01_high_frequency(self):
        f = _features(trades_7d=600)
        t = FilterThresholds()
        reasons = _hard_reject_reasons(f, t, 0.0)
        assert any("500" in r for r in reasons)
        assert any("bot" in r.lower() for r in reasons)

    def test_h02_insufficient_data(self):
        f = _features(total_trades=5)
        t = FilterThresholds()
        reasons = _hard_reject_reasons(f, t, 0.0)
        assert any("below minimum" in r for r in reasons)

    def test_h03_zero_win_rate(self):
        f = _features(win_rate_percent=20.0, total_trades=30)
        t = FilterThresholds()
        reasons = _hard_reject_reasons(f, t, 0.0)
        assert any("win rate" in r.lower() for r in reasons)

    def test_h03_zero_win_rate_not_enough_trades(self):
        # Only 15 trades, should not trigger H-03
        f = _features(win_rate_percent=20.0, total_trades=15)
        t = FilterThresholds()
        reasons = _hard_reject_reasons(f, t, 0.0)
        assert not any("win rate" in r.lower() for r in reasons)

    def test_h04_all_losses(self):
        f = _features(total_profit_usd=-1000, total_trades=60)
        t = FilterThresholds()
        reasons = _hard_reject_reasons(f, t, 0.0)
        assert any("profit" in r.lower() for r in reasons)

    def test_h04_not_enough_trades(self):
        f = _features(total_profit_usd=-1000, total_trades=30)
        t = FilterThresholds()
        reasons = _hard_reject_reasons(f, t, 0.0)
        assert not any("profit" in r.lower() for r in reasons)

    def test_h05_short_holding(self):
        f = _features(avg_holding_hours=0.5, total_trades=120)
        t = FilterThresholds()
        reasons = _hard_reject_reasons(f, t, 0.0)
        assert any("holding" in r.lower() for r in reasons)

    def test_h05_not_enough_trades(self):
        f = _features(avg_holding_hours=0.5, total_trades=50)
        t = FilterThresholds()
        reasons = _hard_reject_reasons(f, t, 0.0)
        assert not any("holding" in r.lower() for r in reasons)

    def test_h06_single_token_gambler(self):
        f = _features(single_token_concentration_percent=85.0)
        t = FilterThresholds()
        reasons = _hard_reject_reasons(f, t, 0.0)
        assert any("concentration" in r.lower() for r in reasons)

    def test_h07_self_transfer(self):
        f = _features(self_transfer_ratio_percent=55.0)
        t = FilterThresholds()
        reasons = _hard_reject_reasons(f, t, 0.0)
        assert any("self-transfer" in r.lower() for r in reasons)

    def test_h08_mev_attacker(self):
        f = _features(is_mev_attacker=True)
        t = FilterThresholds()
        reasons = _hard_reject_reasons(f, t, 0.0)
        assert any("MEV" in r for r in reasons)

    def test_h09_dev_associated(self):
        f = _features(is_dev_associated=True)
        t = FilterThresholds()
        reasons = _hard_reject_reasons(f, t, 0.0)
        assert any("developer" in r.lower() for r in reasons)

    def test_h10_robot_hard_reject(self):
        f = _features()
        t = FilterThresholds()
        reasons = _hard_reject_reasons(f, t, 65.0)
        assert any("robot" in r.lower() for r in reasons)
        assert any("hard reject" in r.lower() for r in reasons)

    def test_h11_inactive(self):
        f = _features(inactive_days=10)
        t = FilterThresholds()
        reasons = _hard_reject_reasons(f, t, 0.0)
        assert any("inactive" in r.lower() for r in reasons)

    def test_multiple_reasons(self):
        f = _features(
            trades_7d=600,
            is_mev_attacker=True,
            total_trades=5,
        )
        t = FilterThresholds()
        reasons = _hard_reject_reasons(f, t, 0.0)
        assert len(reasons) >= 3

    def test_hard_reject_with_robot_data(self):
        f = _features(
            trades_7d=800,
            trade_intervals_seconds=[60.0] * 50,
            avg_holding_hours=0.03,
            fees_sol_list=[0.005] * 50,
            trade_hours_of_day=list(range(24)) * 5,
        )
        result = filter_wallet(f)
        assert result["hard_rejected"] is True
        assert result["decision"] == "reject"
        assert result["score"] == 0
        assert result["robot_score"] >= 60.0


class TestSoftPenalties:
    """Tests for _soft_penalties covering all 10 soft rules."""

    def test_no_penalties_healthy_wallet(self):
        f = _features()
        t = FilterThresholds()
        reasons = []
        penalty = _soft_penalties(f, t, 0.0, reasons)
        assert penalty == 0
        assert reasons == []

    def test_s01_high_frequency_soft(self):
        f = _features(trades_7d=150)
        t = FilterThresholds()
        reasons = []
        penalty = _soft_penalties(f, t, 0.0, reasons)
        assert penalty == 10
        assert any("high frequency" in r.lower() for r in reasons)

    def test_s02_short_holding(self):
        f = _features(avg_holding_hours=4.0)
        t = FilterThresholds()
        reasons = []
        penalty = _soft_penalties(f, t, 0.0, reasons)
        assert penalty == 8
        assert any("short holding" in r.lower() for r in reasons)

    def test_s03_high_volatility(self):
        f = _features(volatility_30d=0.6)
        t = FilterThresholds()
        reasons = []
        penalty = _soft_penalties(f, t, 0.0, reasons)
        assert penalty == 5
        assert any("volatility" in r.lower() for r in reasons)

    def test_s04_turbo_slippage(self):
        f = _features(turbo_slippage_usage_percent=85.0)
        t = FilterThresholds()
        reasons = []
        penalty = _soft_penalties(f, t, 0.0, reasons)
        assert penalty == 5
        assert any("turbo" in r.lower() for r in reasons)

    def test_s05_new_wallet(self):
        f = _features(wallet_age_days=7)
        t = FilterThresholds()
        reasons = []
        penalty = _soft_penalties(f, t, 0.0, reasons)
        assert penalty == 10
        assert any("new wallet" in r.lower() for r in reasons)

    def test_s06_low_diversification(self):
        f = _features(diversification_index=0.2)
        t = FilterThresholds()
        reasons = []
        penalty = _soft_penalties(f, t, 0.0, reasons)
        assert penalty == 8
        assert any("diversification" in r.lower() for r in reasons)

    def test_s07_high_mev(self):
        f = _features(mev_usage_percent=60.0)
        t = FilterThresholds()
        reasons = []
        penalty = _soft_penalties(f, t, 0.0, reasons)
        assert penalty == 5
        assert any("MEV" in r for r in reasons)

    def test_s08_pump_fun_only(self):
        f = _features(pump_fun_interaction_percent=100.0)
        t = FilterThresholds()
        reasons = []
        penalty = _soft_penalties(f, t, 0.0, reasons)
        assert penalty == 10
        assert any("Pump.fun" in r for r in reasons)

    def test_s09_large_gambler(self):
        f = _features(large_gambler_ratio_percent=60.0)
        t = FilterThresholds()
        reasons = []
        penalty = _soft_penalties(f, t, 0.0, reasons)
        assert penalty == 8
        assert any("gambler" in r.lower() for r in reasons)

    def test_s10_low_sl_discipline(self):
        f = _features(stop_loss_trigger_rate_percent=20.0)
        t = FilterThresholds()
        reasons = []
        penalty = _soft_penalties(f, t, 0.0, reasons)
        assert penalty == 5
        assert any("discipline" in r.lower() for r in reasons)

    def test_robot_soft_penalty(self):
        f = _features()
        t = FilterThresholds()
        reasons = []
        penalty = _soft_penalties(f, t, 45.0, reasons)
        assert penalty == 10
        assert any("robot" in r.lower() for r in reasons)

    def test_multiple_penalties_additive(self):
        f = _features(
            trades_7d=150,
            avg_holding_hours=4.0,
            wallet_age_days=7,
            diversification_index=0.2,
        )
        t = FilterThresholds()
        reasons = []
        penalty = _soft_penalties(f, t, 0.0, reasons)
        assert penalty == 36  # 10 + 8 + 10 + 8
        assert len(reasons) == 4

    def test_all_penalties_maximum(self):
        f = _features(
            trades_7d=150,
            avg_holding_hours=4.0,
            volatility_30d=0.6,
            turbo_slippage_usage_percent=85.0,
            wallet_age_days=7,
            diversification_index=0.2,
            mev_usage_percent=60.0,
            pump_fun_interaction_percent=100.0,
            large_gambler_ratio_percent=60.0,
            stop_loss_trigger_rate_percent=20.0,
        )
        t = FilterThresholds()
        reasons = []
        penalty = _soft_penalties(f, t, 45.0, reasons)
        # 10+8+5+5+10+8+5+10+8+5+10 = 84
        assert penalty == 84
        assert len(reasons) == 11


class TestFilterWalletDecision:
    """Integration tests for filter_wallet decision outcomes."""

    def test_pass_healthy_wallet(self):
        f = _features()
        result = filter_wallet(f)
        assert result["hard_rejected"] is False
        assert result["decision"] == "pass"
        assert result["score"] >= 80
        assert result["reasons"] == []

    def test_watch_moderate_penalties(self):
        f = _features(
            trades_7d=150,
            avg_holding_hours=4.0,
            wallet_age_days=7,
        )
        result = filter_wallet(f)
        assert result["hard_rejected"] is False
        assert result["decision"] == "watch"
        assert 60 <= result["score"] < 80

    def test_reject_too_many_penalties(self):
        f = _features(
            trades_7d=150,
            avg_holding_hours=4.0,
            wallet_age_days=7,
            diversification_index=0.2,
            volatility_30d=0.6,
            turbo_slippage_usage_percent=85.0,
            mev_usage_percent=60.0,
            pump_fun_interaction_percent=100.0,
            large_gambler_ratio_percent=60.0,
            stop_loss_trigger_rate_percent=20.0,
        )
        result = filter_wallet(f)
        assert result["hard_rejected"] is False
        assert result["decision"] == "reject"
        assert result["score"] < 60
        assert any("score below watch threshold" in r for r in result["reasons"])

    def test_reject_hard_override(self):
        f = _features(trades_7d=600)
        result = filter_wallet(f)
        assert result["hard_rejected"] is True
        assert result["decision"] == "reject"
        assert result["score"] == 0

    def test_custom_thresholds_change_decision(self):
        f = _features()
        strict = FilterThresholds(pass_score=101, watch_score=101)
        result = filter_wallet(f, strict)
        assert result["decision"] == "reject"
        assert any("score below watch threshold" in r for r in result["reasons"])

    def test_wallet_address_preserved(self):
        f = _features(wallet_address="test123")
        result = filter_wallet(f)
        assert result["wallet_address"] == "test123"

    def test_missing_wallet_address_empty(self):
        f = WalletFeatures.from_dict({})
        result = filter_wallet(f)
        assert result["wallet_address"] == ""

    def test_robot_score_included(self):
        f = _features()
        result = filter_wallet(f)
        assert "robot_score" in result
        assert isinstance(result["robot_score"], float)


class TestFilterConfig:
    """Tests for FilterConfig and load_filter_config."""

    def test_default_config(self):
        config = FilterConfig()
        assert config.for_chain("solana").max_trades_7d == 500
        assert config.for_chain("base").max_trades_7d == 500

    def test_chain_override(self):
        strict = FilterThresholds(max_trades_7d=300)
        config = FilterConfig(chains={"solana": strict})
        assert config.for_chain("solana").max_trades_7d == 300
        assert config.for_chain("base").max_trades_7d == 500

    def test_case_insensitive_chain(self):
        strict = FilterThresholds(max_trades_7d=300)
        config = FilterConfig(chains={"Solana": strict})
        assert config.for_chain("SOLANA").max_trades_7d == 300

    def test_load_config_valid(self, tmp_path):
        config_data = {
            "default": {"max_trades_7d": 400},
            "chains": {"solana": {"max_trades_7d": 200}},
        }
        path = tmp_path / "filter_config.json"
        path.write_text(json.dumps(config_data))
        config = load_filter_config(path)
        assert config.default.max_trades_7d == 400
        assert config.for_chain("solana").max_trades_7d == 200

    def test_load_config_empty_default(self, tmp_path):
        config_data = {"chains": {}}
        path = tmp_path / "filter_config.json"
        path.write_text(json.dumps(config_data))
        config = load_filter_config(path)
        assert config.default.max_trades_7d == 500

    def test_load_config_unknown_field(self, tmp_path):
        path = tmp_path / "bad_config.json"
        path.write_text(json.dumps({"default": {"unknown_field": 1}}))
        with pytest.raises(ValueError, match="unknown filter threshold fields"):
            load_filter_config(path)

    def test_load_config_invalid_json(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not json")
        with pytest.raises(ValueError, match="invalid filter config JSON"):
            load_filter_config(path)

    def test_load_config_non_object(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("[1, 2, 3]")
        with pytest.raises(ValueError, match="filter config must be an object"):
            load_filter_config(path)

    def test_load_config_bad_default_type(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"default": [1, 2]}))
        with pytest.raises(ValueError, match="default filter thresholds must be an object"):
            load_filter_config(path)

    def test_load_config_bad_chains_type(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"chains": [1, 2]}))
        with pytest.raises(ValueError, match="chains filter thresholds must be an object"):
            load_filter_config(path)

    def test_validation_percent_field_exceeds_100(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"default": {"min_win_rate_percent": 150}}))
        with pytest.raises(ValueError, match="must be at most 100"):
            load_filter_config(path)

    def test_validation_pass_score_below_watch(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"default": {"pass_score": 50, "watch_score": 60}}))
        with pytest.raises(ValueError, match="pass_score must be greater than or equal to watch_score"):
            load_filter_config(path)

    def test_validation_robot_hard_below_soft(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"default": {"robot_hard_reject_score": 30, "robot_soft_reject_score": 40}}))
        with pytest.raises(ValueError, match="robot_hard_reject_score must be greater than or equal to"):
            load_filter_config(path)

    def test_validation_negative_value(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"default": {"max_trades_7d": -1}}))
        with pytest.raises(ValueError, match="must be non-negative"):
            load_filter_config(path)

    def test_validation_non_numeric(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"default": {"max_trades_7d": "many"}}))
        with pytest.raises(ValueError, match="must be numeric"):
            load_filter_config(path)


class TestEdgeCases:
    """Boundary and edge-case tests for the filter pipeline."""

    def test_exactly_at_thresholds(self):
        f = _features(
            trades_7d=500,  # exactly at max
            total_trades=10,  # exactly at min
            win_rate_percent=30.0,  # exactly at min
            total_profit_usd=0.0,  # exactly at min
            avg_holding_hours=1.0,  # exactly at min
            single_token_concentration_percent=80.0,  # exactly at max
            self_transfer_ratio_percent=50.0,  # exactly at max
            inactive_days=7,  # exactly at max
        )
        result = filter_wallet(f)
        # At exact thresholds, hard reject should NOT trigger (strict inequality used)
        assert result["hard_rejected"] is False

    def test_just_above_thresholds(self):
        f = _features(
            trades_7d=501,
            single_token_concentration_percent=80.1,
        )
        result = filter_wallet(f)
        assert result["hard_rejected"] is True

    def test_just_below_thresholds(self):
        f = _features(
            trades_7d=499,
            single_token_concentration_percent=79.9,
        )
        result = filter_wallet(f)
        assert result["hard_rejected"] is False

    def test_missing_optional_fields(self):
        f = WalletFeatures.from_dict({
            "wallet_address": "abc",
            "trades_7d": 50,
            "total_trades": 50,
            "win_rate_percent": 60.0,
            "total_profit_usd": 1000.0,
            "avg_holding_hours": 24.0,
            "single_token_concentration_percent": 30.0,
            "self_transfer_ratio_percent": 5.0,
            "inactive_days": 3,
            "wallet_age_days": 90,
            "diversification_index": 0.6,
            "stop_loss_trigger_rate_percent": 50.0,
        })
        result = filter_wallet(f)
        assert result["hard_rejected"] is False
        assert result["decision"] in ("pass", "watch")

    def test_boolean_misuse_as_numeric(self):
        # Booleans should be treated as their numeric values (True=1, False=0)
        f = _features(total_trades=True)  # True -> 1.0
        result = filter_wallet(f)
        assert result["hard_rejected"] is True  # 1 < 10 (min_data_trades)

    def test_invalid_field_types(self):
        f = _features(
            trades_7d="many",
            win_rate_percent="high",
            total_profit_usd="rich",
        )
        result = filter_wallet(f)
        # Invalid values become 0.0, which may trigger some rules
        assert result["hard_rejected"] is True  # total_trades=0 < 10

    def test_score_never_negative(self):
        f = _features(
            trades_7d=150,
            avg_holding_hours=4.0,
            wallet_age_days=7,
            diversification_index=0.2,
            volatility_30d=0.6,
            turbo_slippage_usage_percent=85.0,
            mev_usage_percent=60.0,
            pump_fun_interaction_percent=100.0,
            large_gambler_ratio_percent=60.0,
            stop_loss_trigger_rate_percent=20.0,
        )
        strict = FilterThresholds(pass_score=0, watch_score=0)
        result = filter_wallet(f, strict)
        assert result["score"] >= 0
