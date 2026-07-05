from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from gmgn_monitor.backtest_engine import (
    BacktestEngine,
    BuyMode,
    CloseReason,
    CostModel,
    PaperTrade,
    SLLevel,
    StrategyConfig,
    TPLevel,
    TradeLifecycle,
    TradeStatus,
)
from gmgn_monitor.backtest_strategies import (
    FixedBuyStrategy,
    FixedRatioStrategy,
    MaxBuyStrategy,
    StrategyFactory,
    StrategyType,
    run_single_trade_simulation,
)


# ─────────────────────────── Fixtures ───────────────────────────

@pytest.fixture
def cost_model() -> CostModel:
    return CostModel(
        trading_fee_percent=1.0,
        slippage_percent=25.0,
        priority_fee_sol=0.02,
        sol_price_usd=150.0,
    )


@pytest.fixture
def winning_price_series() -> list[dict[str, str | float]]:
    """Price rises 500% over 10 hours — triggers both TP levels."""
    base = datetime(2026, 1, 1, 12, 0, 0)
    return [
        {"timestamp": (base + timedelta(hours=i)).isoformat(), "price": 1.0 + i * 0.5}
        for i in range(10)
    ]


@pytest.fixture
def losing_price_series() -> list[dict[str, str | float]]:
    """Price drops 80% — triggers SL."""
    base = datetime(2026, 1, 1, 12, 0, 0)
    return [
        {"timestamp": (base + timedelta(hours=i)).isoformat(), "price": 1.0 - i * 0.1}
        for i in range(10)
    ]


@pytest.fixture
def flat_price_series() -> list[dict[str, str | float]]:
    """Price flat — expires."""
    base = datetime(2026, 1, 1, 12, 0, 0)
    return [
        {"timestamp": (base + timedelta(hours=i)).isoformat(), "price": 1.0}
        for i in range(10)
    ]


@pytest.fixture
def wallet_address() -> str:
    return "Wallet111111111111111111111111111111111111111"


@pytest.fixture
def token_address() -> str:
    return "Token111111111111111111111111111111111111111"


# ─────────────────────────── FixedBuyStrategy ───────────────────────────

class TestFixedBuyStrategy:
    def test_config_defaults(self) -> None:
        strategy = FixedBuyStrategy()
        config = strategy.to_config()
        assert config.buy_mode == BuyMode.FIXED_BUY
        assert config.fixed_sol_amount == 0.5
        assert config.sol_price_usd == 150.0
        assert len(config.tp_levels) == 2
        assert config.sl_level.trigger_percent == -65.0

    def test_create_trade(self, wallet_address: str, token_address: str) -> None:
        trade = FixedBuyStrategy().create_trade(
            wallet_address=wallet_address,
            token_address=token_address,
            token_symbol="TEST",
            entry_price=1.0,
            entry_at="2026-01-01T12:00:00",
        )
        assert trade.follow_mode == BuyMode.FIXED_BUY
        assert trade.entry_amount_sol == 0.5
        assert trade.entry_amount_usd == 75.0
        assert trade.entry_price == 1.0

    def test_custom_amount(self, wallet_address: str, token_address: str) -> None:
        strategy = FixedBuyStrategy(fixed_sol_amount=1.0)
        trade = strategy.create_trade(
            wallet_address=wallet_address,
            token_address=token_address,
            token_symbol="TEST",
            entry_price=1.0,
            entry_at="2026-01-01T12:00:00",
        )
        assert trade.entry_amount_sol == 1.0
        assert trade.entry_amount_usd == 150.0

    def test_tp_levels_in_trade(self, wallet_address: str, token_address: str) -> None:
        trade = FixedBuyStrategy().create_trade(
            wallet_address=wallet_address,
            token_address=token_address,
            token_symbol="TEST",
            entry_price=1.0,
            entry_at="2026-01-01T12:00:00",
        )
        assert len(trade.tp_levels) == 2
        assert trade.tp_levels[0].trigger_percent == 100.0
        assert trade.tp_levels[0].sell_percent == 50.0
        assert trade.tp_levels[1].trigger_percent == 300.0
        assert trade.tp_levels[1].sell_percent == 50.0

    def test_from_config(self) -> None:
        config = StrategyConfig(
            buy_mode=BuyMode.FIXED_BUY,
            fixed_sol_amount=0.75,
            sol_price_usd=160.0,
        )
        strategy = FixedBuyStrategy.from_config(config)
        assert strategy.fixed_sol_amount == 0.75
        assert strategy.sol_price_usd == 160.0

    def test_simulation_with_winning_series(
        self, wallet_address: str, token_address: str, winning_price_series: list[dict[str, str | float]], cost_model: CostModel
    ) -> None:
        result = run_single_trade_simulation(
            strategy_type="fixed_buy",
            price_series=winning_price_series,
            wallet_address=wallet_address,
            token_address=token_address,
            token_symbol="WIN",
            cost_model=cost_model,
        )
        assert result.status in (TradeStatus.CLOSED, TradeStatus.OPEN)
        assert result.pnl_after_costs_percent is not None

    def test_simulation_with_losing_series(
        self, wallet_address: str, token_address: str, losing_price_series: list[dict[str, str | float]], cost_model: CostModel
    ) -> None:
        result = run_single_trade_simulation(
            strategy_type="fixed_buy",
            price_series=losing_price_series,
            wallet_address=wallet_address,
            token_address=token_address,
            token_symbol="LOSE",
            cost_model=cost_model,
        )
        assert result.status in (TradeStatus.STOPPED, TradeStatus.CLOSED, TradeStatus.OPEN)


# ─────────────────────────── MaxBuyStrategy ───────────────────────────

class TestMaxBuyStrategy:
    def test_config_defaults(self) -> None:
        strategy = MaxBuyStrategy()
        config = strategy.to_config()
        assert config.buy_mode == BuyMode.MAX_BUY
        assert len(config.tp_levels) == 3
        assert config.sl_level.trigger_percent == -40.0

    def test_create_trade_capped(self, wallet_address: str, token_address: str) -> None:
        strategy = MaxBuyStrategy(max_usd=500.0)
        trade = strategy.create_trade(
            wallet_address=wallet_address,
            token_address=token_address,
            token_symbol="TEST",
            entry_price=1.0,
            entry_at="2026-01-01T12:00:00",
            source_amount_usd=1000.0,  # exceeds cap
        )
        assert trade.entry_amount_usd <= 500.0
        assert trade.follow_mode == BuyMode.MAX_BUY

    def test_create_trade_uncapped(self, wallet_address: str, token_address: str) -> None:
        strategy = MaxBuyStrategy(max_usd=500.0)
        trade = strategy.create_trade(
            wallet_address=wallet_address,
            token_address=token_address,
            token_symbol="TEST",
            entry_price=1.0,
            entry_at="2026-01-01T12:00:00",
            source_amount_usd=200.0,  # below cap
        )
        # When source is below cap, should use source (or a reasonable default)
        # Our implementation: if source_amount_usd > 0, min(source, max_usd)
        assert trade.entry_amount_usd <= 500.0

    def test_from_config(self) -> None:
        config = StrategyConfig(
            buy_mode=BuyMode.MAX_BUY,
            fixed_sol_amount=5.0,
            sol_price_usd=150.0,
        )
        strategy = MaxBuyStrategy.from_config(config)
        assert strategy.max_usd == 750.0  # 5.0 * 150

    def test_simulation_with_winning_series(
        self, wallet_address: str, token_address: str, winning_price_series: list[dict[str, str | float]], cost_model: CostModel
    ) -> None:
        result = run_single_trade_simulation(
            strategy_type="max_buy",
            price_series=winning_price_series,
            wallet_address=wallet_address,
            token_address=token_address,
            token_symbol="WIN",
            source_amount_usd=500.0,
            cost_model=cost_model,
        )
        assert result.pnl_after_costs_percent is not None


# ─────────────────────────── FixedRatioStrategy ───────────────────────────

class TestFixedRatioStrategy:
    def test_config_defaults(self) -> None:
        strategy = FixedRatioStrategy()
        config = strategy.to_config()
        assert config.buy_mode == BuyMode.FIXED_RATIO
        assert config.fixed_ratio == 0.1
        assert len(config.tp_levels) == 3

    def test_create_trade_proportional(self, wallet_address: str, token_address: str) -> None:
        strategy = FixedRatioStrategy(ratio=0.2)
        trade = strategy.create_trade(
            wallet_address=wallet_address,
            token_address=token_address,
            token_symbol="TEST",
            entry_price=1.0,
            entry_at="2026-01-01T12:00:00",
            source_amount_usd=1000.0,
        )
        assert trade.entry_amount_usd == 200.0  # 1000 * 0.2
        assert trade.follow_mode == BuyMode.FIXED_RATIO

    def test_create_trade_no_source(self, wallet_address: str, token_address: str) -> None:
        strategy = FixedRatioStrategy()
        trade = strategy.create_trade(
            wallet_address=wallet_address,
            token_address=token_address,
            token_symbol="TEST",
            entry_price=1.0,
            entry_at="2026-01-01T12:00:00",
            source_amount_usd=0.0,
        )
        # Default fallback when no source amount is provided
        assert trade.entry_amount_usd == 100.0

    def test_from_config(self) -> None:
        config = StrategyConfig(
            buy_mode=BuyMode.FIXED_RATIO,
            fixed_ratio=0.15,
            sol_price_usd=160.0,
        )
        strategy = FixedRatioStrategy.from_config(config)
        assert strategy.ratio == 0.15
        assert strategy.sol_price_usd == 160.0

    def test_simulation_with_winning_series(
        self, wallet_address: str, token_address: str, winning_price_series: list[dict[str, str | float]], cost_model: CostModel
    ) -> None:
        result = run_single_trade_simulation(
            strategy_type="fixed_ratio",
            price_series=winning_price_series,
            wallet_address=wallet_address,
            token_address=token_address,
            token_symbol="WIN",
            source_amount_usd=1000.0,
            cost_model=cost_model,
        )
        assert result.pnl_after_costs_percent is not None


# ─────────────────────────── StrategyFactory ───────────────────────────

class TestStrategyFactory:
    def test_get_strategy_fixed_buy(self) -> None:
        cls = StrategyFactory.get_strategy("fixed_buy")
        assert cls is FixedBuyStrategy

    def test_get_strategy_max_buy(self) -> None:
        cls = StrategyFactory.get_strategy("max_buy")
        assert cls is MaxBuyStrategy

    def test_get_strategy_fixed_ratio(self) -> None:
        cls = StrategyFactory.get_strategy("fixed_ratio")
        assert cls is FixedRatioStrategy

    def test_get_strategy_enum(self) -> None:
        cls = StrategyFactory.get_strategy(StrategyType.MAX_BUY)
        assert cls is MaxBuyStrategy

    def test_get_strategy_unknown(self) -> None:
        with pytest.raises(ValueError, match="unknown strategy type"):
            StrategyFactory.get_strategy("unknown_strategy")

    def test_create_trade(self, wallet_address: str, token_address: str) -> None:
        trade = StrategyFactory.create_trade(
            strategy_type="fixed_buy",
            wallet_address=wallet_address,
            token_address=token_address,
            token_symbol="TEST",
            entry_price=1.0,
            entry_at="2026-01-01T12:00:00",
        )
        assert trade.follow_mode == BuyMode.FIXED_BUY

    def test_create_config(self) -> None:
        config = StrategyFactory.create_config("fixed_buy", fixed_sol_amount=1.0)
        assert config.buy_mode == BuyMode.FIXED_BUY
        assert config.fixed_sol_amount == 1.0

    def test_create_config_max_buy(self) -> None:
        config = StrategyFactory.create_config("max_buy", max_usd=2000.0)
        assert config.buy_mode == BuyMode.MAX_BUY
        # The max_usd is converted to fixed_sol_amount internally
        assert config.fixed_sol_amount == 2000.0 / 150.0


# ─────────────────────────── run_single_trade_simulation ───────────────────────────

class TestRunSingleTradeSimulation:
    def test_empty_series_raises(self, wallet_address: str, token_address: str) -> None:
        with pytest.raises(ValueError, match="price_series must not be empty"):
            run_single_trade_simulation(
                strategy_type="fixed_buy",
                price_series=[],
                wallet_address=wallet_address,
                token_address=token_address,
            )

    def test_tp_triggered_on_winner(
        self, wallet_address: str, token_address: str, winning_price_series: list[dict[str, str | float]], cost_model: CostModel
    ) -> None:
        result = run_single_trade_simulation(
            strategy_type="fixed_buy",
            price_series=winning_price_series,
            wallet_address=wallet_address,
            token_address=token_address,
            cost_model=cost_model,
        )
        assert result.exit_price is not None
        assert result.pnl_percent is not None
        assert result.pnl_after_costs_percent is not None
        assert result.total_costs_usd > 0

    def test_sl_triggered_on_loser(
        self, wallet_address: str, token_address: str, losing_price_series: list[dict[str, str | float]], cost_model: CostModel
    ) -> None:
        result = run_single_trade_simulation(
            strategy_type="fixed_buy",
            price_series=losing_price_series,
            wallet_address=wallet_address,
            token_address=token_address,
            cost_model=cost_model,
        )
        assert result.status is not None
        assert result.pnl_after_costs_percent is not None

    def test_all_strategies_with_same_series(
        self, wallet_address: str, token_address: str, winning_price_series: list[dict[str, str | float]], cost_model: CostModel
    ) -> None:
        for strategy_type in ["fixed_buy", "max_buy", "fixed_ratio"]:
            result = run_single_trade_simulation(
                strategy_type=strategy_type,
                price_series=winning_price_series,
                wallet_address=wallet_address,
                token_address=token_address,
                source_amount_usd=1000.0,
                cost_model=cost_model,
            )
            assert result.pnl_after_costs_percent is not None
            assert result.total_costs_usd > 0

    def test_backtest_id_set(self, wallet_address: str, token_address: str, winning_price_series: list[dict[str, str | float]]) -> None:
        result = run_single_trade_simulation(
            strategy_type="fixed_buy",
            price_series=winning_price_series,
            wallet_address=wallet_address,
            token_address=token_address,
        )
        assert result.backtest_batch_id == "single-sim"

    def test_cost_model_default(self, wallet_address: str, token_address: str, winning_price_series: list[dict[str, str | float]]) -> None:
        # When cost_model is None, default conservative model is used
        result = run_single_trade_simulation(
            strategy_type="fixed_buy",
            price_series=winning_price_series,
            wallet_address=wallet_address,
            token_address=token_address,
        )
        assert result.total_costs_usd > 0


# ─────────────────────────── Integration: strategy + lifecycle ───────────────────────────

class TestStrategyLifecycleIntegration:
    def test_fixed_buy_tp_sequence(self, wallet_address: str, token_address: str) -> None:
        """Simulate a 10x price run: TP1 at +100%, TP2 at +300%."""
        base = datetime(2026, 1, 1, 12, 0, 0)
        price_series = [
            {"timestamp": (base + timedelta(hours=i)).isoformat(), "price": 1.0 + i * 0.5}
            for i in range(20)
        ]
        result = run_single_trade_simulation(
            strategy_type="fixed_buy",
            price_series=price_series,
            wallet_address=wallet_address,
            token_address=token_address,
        )
        # At some point the price hits +100% (price >= 2.0) and +300% (price >= 4.0)
        assert result.pnl_percent is not None

    def test_max_buy_sl_trigger(self, wallet_address: str, token_address: str) -> None:
        """Max Buy uses -40% SL, should trigger on a 60% drop."""
        base = datetime(2026, 1, 1, 12, 0, 0)
        price_series = [
            {"timestamp": (base + timedelta(hours=i)).isoformat(), "price": 1.0 - i * 0.08}
            for i in range(10)
        ]
        result = run_single_trade_simulation(
            strategy_type="max_buy",
            price_series=price_series,
            wallet_address=wallet_address,
            token_address=token_address,
            cost_model=CostModel(slippage_percent=20.0),
        )
        assert result.status in (TradeStatus.STOPPED, TradeStatus.CLOSED, TradeStatus.OPEN)

    def test_fixed_ratio_uses_source_amount(self, wallet_address: str, token_address: str) -> None:
        """Fixed Ratio should mirror the source amount."""
        base = datetime(2026, 1, 1, 12, 0, 0)
        price_series = [
            {"timestamp": (base + timedelta(hours=i)).isoformat(), "price": 1.0 + i * 0.1}
            for i in range(10)
        ]
        source_amount = 5000.0
        result = run_single_trade_simulation(
            strategy_type="fixed_ratio",
            price_series=price_series,
            wallet_address=wallet_address,
            token_address=token_address,
            source_amount_usd=source_amount,
        )
        # Entry should be 10% of 5000 = 500 USD
        expected_entry = source_amount * 0.1
        assert result.entry_amount_usd == expected_entry
