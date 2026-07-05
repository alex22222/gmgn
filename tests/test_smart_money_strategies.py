from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from gmgn_monitor.backtest_engine import BacktestEngine, StrategyConfig
from gmgn_monitor.backtest_strategies import (
    BuySignal,
    FixedBuyStrategy,
    SmartMoneyCopyStrategy,
    SignalFollowStrategy,
    TrailingStopStrategy,
    StrategyFactory,
)


class TestSmartMoneyCopyStrategy:
    def test_config_generation(self) -> None:
        strategy = SmartMoneyCopyStrategy(
            target_wallet_address="Wallet111111111111111111111111111111111111",
            copy_ratio=0.2,
            max_position_sol=2.0,
        )
        config = strategy.to_config()
        assert config.buy_mode.value == "fixed_ratio"
        assert config.fixed_ratio == 0.2
        assert config.fixed_sol_amount == 0.5  # min(2.0, 0.5)

    def test_generate_signals_from_activity(self) -> None:
        strategy = SmartMoneyCopyStrategy(target_wallet_address="Wallet1")
        activity = [
            {"token_address": "TOKEN_A", "action": "buy", "price": 1.0, "amount": 0.5, "timestamp": "2025-07-01T10:00:00Z"},
            {"token_address": "TOKEN_B", "action": "buy", "price": 2.0, "amount": 1.0, "timestamp": "2025-07-01T11:00:00Z"},
            {"token_address": "TOKEN_A", "action": "sell", "price": 1.5, "amount": 0.5, "timestamp": "2025-07-01T12:00:00Z"},
        ]
        signals = strategy.generate_signals(activity)
        assert len(signals) == 2  # sell excluded
        assert signals[0].token_address == "TOKEN_A"
        assert signals[0].wallet_address == "Wallet1"
        assert signals[0].price_usd == 1.0

    def test_tp_levels_in_config(self) -> None:
        strategy = SmartMoneyCopyStrategy(target_wallet_address="w1")
        config = strategy.to_config()
        assert len(config.tp_levels) == 2
        assert config.tp_levels[0].trigger_percent == 100.0
        assert config.sl_level.trigger_percent == -65.0

    def test_factory_registration(self) -> None:
        config = StrategyFactory.create_config("smart_money_copy", target_wallet_address="w1")
        assert config.buy_mode.value == "fixed_ratio"


class TestSignalFollowStrategy:
    def test_config_generation(self) -> None:
        strategy = SignalFollowStrategy(
            min_wallet_count=5,
            time_window_hours=12,
            buy_amount_sol=1.0,
        )
        config = strategy.to_config()
        assert config.buy_mode.value == "fixed_buy"
        assert config.fixed_sol_amount == 1.0

    def test_generate_consensus_signals(self) -> None:
        strategy = SignalFollowStrategy(min_wallet_count=3, time_window_hours=6)
        wallet_activities = [
            [
                {"wallet_address": "w1", "token_address": "TOKEN_X", "action": "buy", "price": 1.0, "amount": 0.5, "timestamp": "2025-07-01T10:00:00Z", "confidence": 0.8},
            ],
            [
                {"wallet_address": "w2", "token_address": "TOKEN_X", "action": "buy", "price": 1.1, "amount": 0.6, "timestamp": "2025-07-01T10:30:00Z", "confidence": 0.7},
            ],
            [
                {"wallet_address": "w3", "token_address": "TOKEN_X", "action": "buy", "price": 1.2, "amount": 0.4, "timestamp": "2025-07-01T11:00:00Z", "confidence": 0.9},
            ],
        ]
        signals = strategy.generate_consensus_signals(wallet_activities)
        assert len(signals) == 1
        assert signals[0].token_address == "TOKEN_X"
        assert signals[0].wallet_address == "consensus"

    def test_no_consensus_below_threshold(self) -> None:
        strategy = SignalFollowStrategy(min_wallet_count=5)
        wallet_activities = [
            [
                {"wallet_address": "w1", "token_address": "TOKEN_X", "action": "buy", "price": 1.0, "amount": 0.5, "timestamp": "2025-07-01T10:00:00Z", "confidence": 0.8},
            ],
            [
                {"wallet_address": "w2", "token_address": "TOKEN_X", "action": "buy", "price": 1.1, "amount": 0.6, "timestamp": "2025-07-01T10:30:00Z", "confidence": 0.7},
            ],
        ]
        signals = strategy.generate_consensus_signals(wallet_activities)
        assert len(signals) == 0

    def test_consensus_outside_time_window(self) -> None:
        strategy = SignalFollowStrategy(min_wallet_count=3, time_window_hours=1)
        wallet_activities = [
            [
                {"wallet_address": "w1", "token_address": "TOKEN_X", "action": "buy", "price": 1.0, "amount": 0.5, "timestamp": "2025-07-01T10:00:00Z", "confidence": 0.8},
            ],
            [
                {"wallet_address": "w2", "token_address": "TOKEN_X", "action": "buy", "price": 1.1, "amount": 0.6, "timestamp": "2025-07-01T10:30:00Z", "confidence": 0.7},
            ],
            [
                {"wallet_address": "w3", "token_address": "TOKEN_X", "action": "buy", "price": 1.2, "amount": 0.4, "timestamp": "2025-07-01T12:00:00Z", "confidence": 0.9},
            ],
        ]
        signals = strategy.generate_consensus_signals(wallet_activities)
        assert len(signals) == 0

    def test_factory_registration(self) -> None:
        config = StrategyFactory.create_config("signal_follow")
        assert config.buy_mode.value == "fixed_buy"


class TestTrailingStopStrategy:
    def test_config_generation(self) -> None:
        strategy = TrailingStopStrategy(
            fixed_sol_amount=0.5,
            trailing_stop_percent=25.0,
            min_profit_percent=50.0,
        )
        config = strategy.to_config()
        assert config.buy_mode.value == "fixed_buy"
        assert config.fixed_sol_amount == 0.5
        assert config.sl_level.trigger_percent == -65.0  # class default, not -25.0
        assert config.max_holding_days == 30

    def test_create_trade(self) -> None:
        strategy = TrailingStopStrategy()
        trade = strategy.create_trade(
            wallet_address="Wallet1",
            token_address="TOKEN_A",
            token_symbol="TEST",
            entry_price=1.0,
            entry_at="2025-07-01T10:00:00Z",
        )
        assert trade.entry_amount_sol == 0.5
        assert trade.entry_amount_usd == 75.0

    def test_factory_registration(self) -> None:
        config = StrategyFactory.create_config("trailing_stop")
        assert config.buy_mode.value == "fixed_buy"


class TestSignalBacktest:
    def test_run_signal_backtest(self) -> None:
        engine = BacktestEngine()
        signals = [
            BuySignal(
                wallet_address="w1",
                token_address="TOKEN_A",
                timestamp="2025-07-01T00:00:00Z",
                price_usd=1.0,
                amount_sol=0.5,
                confidence=0.8,
            ),
        ]
        price_data = {
            "TOKEN_A": [
                {"timestamp": "2025-07-01T00:00:00Z", "price": 1.0},
                {"timestamp": "2025-07-01T01:00:00Z", "price": 2.0},
                {"timestamp": "2025-07-01T02:00:00Z", "price": 3.0},
            ],
        }
        strategy = FixedBuyStrategy().to_config()
        result = engine.run_signal_backtest("w1", signals, price_data, strategy)
        assert result.total_trades == 1
        assert result.wallet_address == "w1"

    def test_run_signal_backtest_empty_signals(self) -> None:
        engine = BacktestEngine()
        result = engine.run_signal_backtest("w1", [], {}, FixedBuyStrategy().to_config())
        assert result.total_trades == 0

    def test_run_signal_backtest_missing_token(self) -> None:
        engine = BacktestEngine()
        signals = [
            BuySignal(
                wallet_address="w1",
                token_address="TOKEN_MISSING",
                timestamp="2025-07-01T00:00:00Z",
                price_usd=1.0,
                amount_sol=0.5,
                confidence=0.8,
            ),
        ]
        result = engine.run_signal_backtest("w1", signals, {}, FixedBuyStrategy().to_config())
        assert result.total_trades == 0

    def test_signal_backtest_with_smart_money_copy_strategy(self) -> None:
        strategy = SmartMoneyCopyStrategy(target_wallet_address="w1")
        config = strategy.to_config()
        assert config.buy_mode.value == "fixed_ratio"
        assert config.fixed_ratio == 0.1

    def test_signal_backtest_with_signal_follow_strategy(self) -> None:
        strategy = SignalFollowStrategy(min_wallet_count=3)
        config = strategy.to_config()
        assert config.fixed_sol_amount == 0.5
        assert len(config.tp_levels) == 2
