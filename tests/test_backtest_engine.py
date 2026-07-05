from __future__ import annotations

from datetime import datetime, timedelta
from math import isfinite
from uuid import uuid4

import pytest

from gmgn_monitor.backtest_engine import (
    BacktestEngine,
    BacktestResult,
    BuyMode,
    CloseReason,
    CostModel,
    PaperTrade,
    SLLevel,
    StrategyConfig,
    TPLevel,
    TradeLifecycle,
    TradeStatus,
    WalkForwardWindow,
)


# ─────────────────────────── Fixtures ───────────────────────────

@pytest.fixture
def default_cost_model() -> CostModel:
    return CostModel(
        trading_fee_percent=1.0,
        slippage_percent=25.0,
        priority_fee_sol=0.02,
        sol_price_usd=150.0,
    )


@pytest.fixture
def base_strategy_config() -> StrategyConfig:
    return StrategyConfig(
        buy_mode=BuyMode.FIXED_BUY,
        fixed_sol_amount=0.5,
        sol_price_usd=150.0,
        trading_fee_percent=1.0,
        slippage_percent=25.0,
        priority_fee_sol=0.02,
        tp_levels=(
            TPLevel(level=1, trigger_percent=100.0, sell_percent=50.0),
            TPLevel(level=2, trigger_percent=300.0, sell_percent=50.0),
        ),
        sl_level=SLLevel(trigger_percent=-65.0),
    )


@pytest.fixture
def winning_price_series() -> list[dict[str, str | float]]:
    """Price goes up 500% — should trigger both TP levels."""
    base = datetime(2026, 1, 1, 12, 0, 0)
    return [
        {"timestamp": (base + timedelta(hours=i)).isoformat(), "price": 1.0 + i * 0.5}
        for i in range(10)
    ]


@pytest.fixture
def losing_price_series() -> list[dict[str, str | float]]:
    """Price drops 80% — should trigger SL."""
    base = datetime(2026, 1, 1, 12, 0, 0)
    return [
        {"timestamp": (base + timedelta(hours=i)).isoformat(), "price": 1.0 - i * 0.1}
        for i in range(10)
    ]


@pytest.fixture
def flat_price_series() -> list[dict[str, str | float]]:
    """Price stays flat — should expire."""
    base = datetime(2026, 1, 1, 12, 0, 0)
    return [
        {"timestamp": (base + timedelta(hours=i)).isoformat(), "price": 1.0}
        for i in range(10)
    ]


@pytest.fixture
def paper_trade(base_strategy_config: StrategyConfig) -> PaperTrade:
    return PaperTrade(
        trade_id=str(uuid4()),
        wallet_address="Wallet111111111111111111111111111111111111111",
        token_address="Token111111111111111111111111111111111111111",
        token_symbol="TEST",
        follow_mode=BuyMode.FIXED_BUY,
        entry_price=1.0,
        entry_amount_usd=75.0,
        entry_amount_sol=0.5,
        entry_at=datetime(2026, 1, 1, 12, 0, 0).isoformat(),
        tp_levels=base_strategy_config.tp_levels,
        sl_level=base_strategy_config.sl_level,
        backtest_batch_id="bt-001",
        created_at=datetime.now().isoformat(),
    )


# ─────────────────────────── CostModel ───────────────────────────

class TestCostModel:
    def test_entry_costs_computation(self, default_cost_model: CostModel) -> None:
        costs = default_cost_model.entry_costs(100.0)
        assert costs["fee_usd"] == 1.0
        assert costs["slippage_usd"] == 25.0
        assert costs["priority_fee_usd"] == 3.0  # 0.02 * 150
        assert costs["total_costs_usd"] == 29.0

    def test_exit_costs_symmetry(self, default_cost_model: CostModel) -> None:
        entry = default_cost_model.entry_costs(100.0)
        exit = default_cost_model.exit_costs(100.0)
        assert entry == exit

    def test_round_trip_costs(self, default_cost_model: CostModel) -> None:
        costs = default_cost_model.round_trip_costs(100.0, 150.0)
        # entry: fee=1, slippage=25, priority=3 → 29
        # exit: fee=1.5, slippage=37.5, priority=3 → 42
        assert costs["total_costs_usd"] == 71.0
        assert costs["fee_usd"] == 2.5
        assert costs["slippage_usd"] == 62.5

    def test_zero_amount(self, default_cost_model: CostModel) -> None:
        costs = default_cost_model.entry_costs(0.0)
        assert costs["total_costs_usd"] == 3.0  # only priority fee remains

    def test_negative_amount_raises_no_error_but_is_unsafe(self, default_cost_model: CostModel) -> None:
        # CostModel does not validate inputs; it just computes
        costs = default_cost_model.entry_costs(-50.0)
        assert costs["fee_usd"] == -0.5
        assert costs["slippage_usd"] == -12.5


# ─────────────────────────── TradeLifecycle ───────────────────────────

class TestTradeLifecycle:
    def test_tp_triggered(self, paper_trade: PaperTrade, default_cost_model: CostModel) -> None:
        lifecycle = TradeLifecycle(paper_trade)
        # Price rises 150% — triggers TP level 1 (+100%) but not TP level 2 (+300%)
        lifecycle.update_price(2.5, "2026-01-01T14:00:00")
        # Partial close: 50% sold, 50% remaining
        assert lifecycle.remaining_position == 50.0
        assert lifecycle.status == TradeStatus.OPEN

    def test_tp_fully_triggered(self, paper_trade: PaperTrade, default_cost_model: CostModel) -> None:
        lifecycle = TradeLifecycle(paper_trade)
        # Price rises 400% — triggers both TP levels
        lifecycle.update_price(5.0, "2026-01-01T18:00:00")
        assert lifecycle.remaining_position == 0.0
        assert lifecycle.status == TradeStatus.CLOSED
        finalized = lifecycle.finalize(default_cost_model)
        assert finalized.exit_price is not None

    def test_sl_triggered(self, paper_trade: PaperTrade, default_cost_model: CostModel) -> None:
        lifecycle = TradeLifecycle(paper_trade)
        lifecycle.update_price(0.2, "2026-01-01T14:00:00")  # -80%
        assert lifecycle.status == TradeStatus.STOPPED
        finalized = lifecycle.finalize(default_cost_model)
        assert finalized.close_reason == CloseReason.SL

    def test_no_trigger(self, paper_trade: PaperTrade, default_cost_model: CostModel) -> None:
        lifecycle = TradeLifecycle(paper_trade)
        lifecycle.update_price(1.2, "2026-01-01T13:00:00")  # +20%, no TP/SL
        assert lifecycle.status == TradeStatus.OPEN

    def test_idempotency_after_close(self, paper_trade: PaperTrade) -> None:
        lifecycle = TradeLifecycle(paper_trade)
        lifecycle.update_price(0.2, "2026-01-01T14:00:00")
        assert lifecycle.status == TradeStatus.STOPPED
        lifecycle.update_price(0.5, "2026-01-01T15:00:00")
        assert lifecycle.status == TradeStatus.STOPPED  # unchanged

    def test_liquidation(self, paper_trade: PaperTrade, default_cost_model: CostModel) -> None:
        lifecycle = TradeLifecycle(paper_trade)
        lifecycle.update_price(0.0, "2026-01-01T14:00:00")
        assert lifecycle.status == TradeStatus.LIQUIDATED

    def test_finalize_computes_pnl(self, paper_trade: PaperTrade, default_cost_model: CostModel) -> None:
        lifecycle = TradeLifecycle(paper_trade)
        lifecycle.update_price(2.0, "2026-01-01T14:00:00")
        lifecycle._execute_expiry(2.0, "2026-01-01T14:00:00")  # type: ignore[misc]
        finalized = lifecycle.finalize(default_cost_model)
        assert finalized.pnl_percent is not None
        assert finalized.pnl_after_costs_percent is not None
        assert finalized.realized_pnl_usd is not None
        assert finalized.total_costs_usd > 0
        assert finalized.holding_duration_minutes is not None

    def test_zero_entry_price_is_safe(self, paper_trade: PaperTrade) -> None:
        trade = PaperTrade(
            **{**paper_trade.to_dict(), "entry_price": 0.0}
        )
        lifecycle = TradeLifecycle(trade)
        lifecycle.update_price(1.0, "2026-01-01T14:00:00")
        assert lifecycle.status == TradeStatus.OPEN  # no division by zero


# ─────────────────────────── BacktestEngine ───────────────────────────

class TestBacktestEngine:
    def test_run_backtest_basic(self, base_strategy_config: StrategyConfig) -> None:
        engine = BacktestEngine()
        price_data = {
            "TOKEN1": [
                {"timestamp": "2026-01-01T12:00:00", "price": 1.0},
                {"timestamp": "2026-01-01T13:00:00", "price": 2.0},
                {"timestamp": "2026-01-01T14:00:00", "price": 1.5},
            ],
        }
        result = engine.run_backtest(
            wallet_address="Wallet111111111111111111111111111111111111111",
            price_data=price_data,
            strategy_config=base_strategy_config,
            backtest_id="bt-001",
        )
        assert isinstance(result, BacktestResult)
        assert result.backtest_id == "bt-001"
        assert result.total_trades == 1
        assert result.period_start == "2026-01-01T12:00:00"
        assert result.period_end == "2026-01-01T14:00:00"
        assert result.generated_at

    def test_run_backtest_multiple_tokens(self, base_strategy_config: StrategyConfig) -> None:
        engine = BacktestEngine()
        price_data = {
            "TOKEN1": [
                {"timestamp": "2026-01-01T12:00:00", "price": 1.0},
                {"timestamp": "2026-01-01T14:00:00", "price": 2.0},
            ],
            "TOKEN2": [
                {"timestamp": "2026-01-01T12:00:00", "price": 1.0},
                {"timestamp": "2026-01-01T14:00:00", "price": 0.5},
            ],
        }
        result = engine.run_backtest(
            wallet_address="Wallet111111111111111111111111111111111111111",
            price_data=price_data,
            strategy_config=base_strategy_config,
            backtest_id="bt-002",
        )
        assert result.total_trades == 2

    def test_empty_price_data(self, base_strategy_config: StrategyConfig) -> None:
        engine = BacktestEngine()
        result = engine.run_backtest(
            wallet_address="Wallet111111111111111111111111111111111111111",
            price_data={},
            strategy_config=base_strategy_config,
            backtest_id="bt-empty",
        )
        assert result.total_trades == 0
        assert result.total_return_percent == 0.0

    def test_positive_expectancy_detection(self, base_strategy_config: StrategyConfig) -> None:
        engine = BacktestEngine()
        # Strong winner: 10x price increase
        price_data = {
            "TOKEN1": [
                {"timestamp": "2026-01-01T12:00:00", "price": 1.0},
                {"timestamp": "2026-01-02T12:00:00", "price": 10.0},
            ],
        }
        result = engine.run_backtest(
            wallet_address="Wallet111111111111111111111111111111111111111",
            price_data=price_data,
            strategy_config=base_strategy_config,
        )
        assert result.is_positive_expectancy() is True
        assert result.expectancy_after_costs_percent > 0

    def test_negative_expectancy_detection(self, base_strategy_config: StrategyConfig) -> None:
        engine = BacktestEngine()
        # Big loser: 90% drop
        price_data = {
            "TOKEN1": [
                {"timestamp": "2026-01-01T12:00:00", "price": 1.0},
                {"timestamp": "2026-01-02T12:00:00", "price": 0.1},
            ],
        }
        result = engine.run_backtest(
            wallet_address="Wallet111111111111111111111111111111111111111",
            price_data=price_data,
            strategy_config=base_strategy_config,
        )
        assert result.is_positive_expectancy() is False

    def test_go_no_go_gate(self, base_strategy_config: StrategyConfig) -> None:
        engine = BacktestEngine()
        price_data = {
            "TOKEN1": [
                {"timestamp": "2026-01-01T12:00:00", "price": 1.0},
                {"timestamp": "2026-01-02T12:00:00", "price": 10.0},
            ],
            "TOKEN2": [
                {"timestamp": "2026-01-01T12:00:00", "price": 1.0},
                {"timestamp": "2026-01-02T12:00:00", "price": 2.0},
            ],
        }
        result = engine.run_backtest(
            wallet_address="Wallet111111111111111111111111111111111111111",
            price_data=price_data,
            strategy_config=base_strategy_config,
        )
        # A 10x winner + 2x winner should pass the default Go/No-Go gate
        assert result.passes_go_no_go() is True

    def test_go_no_go_fails_on_poor_performance(self, base_strategy_config: StrategyConfig) -> None:
        engine = BacktestEngine()
        price_data = {
            "TOKEN1": [
                {"timestamp": "2026-01-01T12:00:00", "price": 1.0},
                {"timestamp": "2026-01-02T12:00:00", "price": 0.5},
            ],
        }
        result = engine.run_backtest(
            wallet_address="Wallet111111111111111111111111111111111111111",
            price_data=price_data,
            strategy_config=base_strategy_config,
        )
        assert result.passes_go_no_go() is False

    def test_equity_curve_populated(self, base_strategy_config: StrategyConfig) -> None:
        engine = BacktestEngine()
        price_data = {
            "TOKEN1": [
                {"timestamp": "2026-01-01T12:00:00", "price": 1.0},
                {"timestamp": "2026-01-02T12:00:00", "price": 2.0},
            ],
            "TOKEN2": [
                {"timestamp": "2026-01-01T12:00:00", "price": 1.0},
                {"timestamp": "2026-01-02T12:00:00", "price": 0.5},
            ],
        }
        result = engine.run_backtest(
            wallet_address="Wallet111111111111111111111111111111111111111",
            price_data=price_data,
            strategy_config=base_strategy_config,
        )
        assert len(result.equity_curve) == 2
        assert "timestamp" in result.equity_curve[0]
        assert "equity" in result.equity_curve[0]

    def test_daily_returns_populated(self, base_strategy_config: StrategyConfig) -> None:
        engine = BacktestEngine()
        price_data = {
            "TOKEN1": [
                {"timestamp": "2026-01-01T12:00:00", "price": 1.0},
                {"timestamp": "2026-01-02T12:00:00", "price": 2.0},
            ],
        }
        result = engine.run_backtest(
            wallet_address="Wallet111111111111111111111111111111111111111",
            price_data=price_data,
            strategy_config=base_strategy_config,
        )
        assert len(result.daily_returns) >= 1

    def test_costs_are_deducted(self, base_strategy_config: StrategyConfig) -> None:
        engine = BacktestEngine()
        price_data = {
            "TOKEN1": [
                {"timestamp": "2026-01-01T12:00:00", "price": 1.0},
                {"timestamp": "2026-01-02T12:00:00", "price": 2.0},
            ],
        }
        result = engine.run_backtest(
            wallet_address="Wallet111111111111111111111111111111111111111",
            price_data=price_data,
            strategy_config=base_strategy_config,
        )
        assert result.total_fees_usd > 0
        assert result.total_slippage_usd > 0
        assert result.total_priority_fees_usd > 0
        assert result.total_costs_percent > 0


# ─────────────────────────── Walk-Forward ───────────────────────────

class TestWalkForward:
    def test_walk_forward_windows(self, base_strategy_config: StrategyConfig) -> None:
        engine = BacktestEngine()
        # 30 days of data, enough for 2 walk-forward windows
        base = datetime(2026, 1, 1)
        price_data = {
            "TOKEN1": [
                {"timestamp": (base + timedelta(days=i)).isoformat(), "price": 1.0 + (i % 5) * 0.1}
                for i in range(30)
            ],
        }
        windows = engine.walk_forward(
            wallet_address="Wallet111111111111111111111111111111111111111",
            price_data=price_data,
            strategy_config=base_strategy_config,
            train_window_days=14,
            test_window_days=7,
        )
        assert len(windows) >= 1
        for w in windows:
            assert isinstance(w, WalkForwardWindow)
            assert w.test_result is not None
            assert w.train_start
            assert w.test_end

    def test_walk_forward_empty_data(self, base_strategy_config: StrategyConfig) -> None:
        engine = BacktestEngine()
        windows = engine.walk_forward(
            wallet_address="Wallet111111111111111111111111111111111111111",
            price_data={},
            strategy_config=base_strategy_config,
        )
        assert windows == []

    def test_walk_forward_short_data(self, base_strategy_config: StrategyConfig) -> None:
        engine = BacktestEngine()
        base = datetime(2026, 1, 1)
        price_data = {
            "TOKEN1": [
                {"timestamp": (base + timedelta(days=i)).isoformat(), "price": 1.0}
                for i in range(5)
            ],
        }
        windows = engine.walk_forward(
            wallet_address="Wallet111111111111111111111111111111111111111",
            price_data=price_data,
            strategy_config=base_strategy_config,
            train_window_days=14,
            test_window_days=7,
        )
        assert windows == []

    def test_compare_strategies(self, base_strategy_config: StrategyConfig) -> None:
        engine = BacktestEngine()
        price_data = {
            "TOKEN1": [
                {"timestamp": "2026-01-01T12:00:00", "price": 1.0},
                {"timestamp": "2026-01-02T12:00:00", "price": 2.0},
            ],
        }
        strategies = [
            base_strategy_config,
            StrategyConfig(
                buy_mode=BuyMode.FIXED_RATIO,
                fixed_ratio=0.2,
                tp_levels=(
                    TPLevel(level=1, trigger_percent=50.0, sell_percent=50.0),
                ),
                sl_level=SLLevel(trigger_percent=-30.0),
            ),
        ]
        results = engine.compare_strategies(
            wallet_address="Wallet111111111111111111111111111111111111111",
            price_data=price_data,
            strategies=strategies,
        )
        assert len(results) == 2
        # Results should be sorted: positive expectancy first
        assert results[0].expectancy_after_costs_percent >= results[1].expectancy_after_costs_percent


# ─────────────────────────── StrategyConfig ───────────────────────────

class TestStrategyConfig:
    def test_to_dict_roundtrip(self, base_strategy_config: StrategyConfig) -> None:
        d = base_strategy_config.to_dict()
        restored = StrategyConfig.from_dict(d)
        assert restored.buy_mode == base_strategy_config.buy_mode
        assert restored.fixed_sol_amount == base_strategy_config.fixed_sol_amount
        assert len(restored.tp_levels) == len(base_strategy_config.tp_levels)
        assert restored.sl_level.trigger_percent == base_strategy_config.sl_level.trigger_percent

    def test_from_dict_with_custom_tp(self) -> None:
        d = {
            "buy_mode": "max_buy",
            "fixed_sol_amount": 1.0,
            "fixed_ratio": 0.15,
            "sol_price_usd": 160.0,
            "trading_fee_percent": 1.5,
            "slippage_percent": 30.0,
            "priority_fee_sol": 0.05,
            "max_holding_days": 5,
            "tp_levels": [
                {"level": 1, "trigger_percent": 50.0, "sell_percent": 30.0},
                {"level": 2, "trigger_percent": 200.0, "sell_percent": 70.0},
            ],
            "sl_level": {"trigger_percent": -50.0, "sell_percent": 100.0},
        }
        config = StrategyConfig.from_dict(d)
        assert config.buy_mode == BuyMode.MAX_BUY
        assert config.sol_price_usd == 160.0
        assert len(config.tp_levels) == 2
        assert config.sl_level.trigger_percent == -50.0

    def test_defaults(self) -> None:
        config = StrategyConfig()
        assert config.buy_mode == BuyMode.FIXED_BUY
        assert config.fixed_sol_amount == 0.5
        assert config.slippage_percent == 25.0
        assert config.max_holding_days == 7


# ─────────────────────────── BacktestResult ───────────────────────────

class TestBacktestResult:
    def test_positive_expectancy_true(self) -> None:
        result = BacktestResult(
            backtest_id="bt-001",
            wallet_address="Wallet111111111111111111111111111111111111111",
            strategy_config=StrategyConfig(),
            period_start="2026-01-01",
            period_end="2026-01-02",
            expectancy_after_costs_percent=1.5,
            total_trades=10,
        )
        assert result.is_positive_expectancy() is True

    def test_positive_expectancy_false(self) -> None:
        result = BacktestResult(
            backtest_id="bt-001",
            wallet_address="Wallet111111111111111111111111111111111111111",
            strategy_config=StrategyConfig(),
            period_start="2026-01-01",
            period_end="2026-01-02",
            expectancy_after_costs_percent=-0.5,
            total_trades=10,
        )
        assert result.is_positive_expectancy() is False

    def test_go_no_go_all_pass(self) -> None:
        result = BacktestResult(
            backtest_id="bt-001",
            wallet_address="Wallet111111111111111111111111111111111111111",
            strategy_config=StrategyConfig(),
            period_start="2026-01-01",
            period_end="2026-01-02",
            expectancy_after_costs_percent=5.0,
            sharpe_ratio=1.0,
            max_drawdown_percent=-10.0,
            win_rate=60.0,
            total_trades=10,
        )
        assert result.passes_go_no_go() is True

    def test_go_no_go_fails_expectancy(self) -> None:
        result = BacktestResult(
            backtest_id="bt-001",
            wallet_address="Wallet111111111111111111111111111111111111111",
            strategy_config=StrategyConfig(),
            period_start="2026-01-01",
            period_end="2026-01-02",
            expectancy_after_costs_percent=-1.0,
            sharpe_ratio=1.0,
            max_drawdown_percent=-10.0,
            win_rate=60.0,
            total_trades=10,
        )
        assert result.passes_go_no_go() is False

    def test_go_no_go_fails_sharpe(self) -> None:
        result = BacktestResult(
            backtest_id="bt-001",
            wallet_address="Wallet111111111111111111111111111111111111111",
            strategy_config=StrategyConfig(),
            period_start="2026-01-01",
            period_end="2026-01-02",
            expectancy_after_costs_percent=5.0,
            sharpe_ratio=0.3,
            max_drawdown_percent=-10.0,
            win_rate=60.0,
            total_trades=10,
        )
        assert result.passes_go_no_go() is False

    def test_go_no_go_fails_drawdown(self) -> None:
        result = BacktestResult(
            backtest_id="bt-001",
            wallet_address="Wallet111111111111111111111111111111111111111",
            strategy_config=StrategyConfig(),
            period_start="2026-01-01",
            period_end="2026-01-02",
            expectancy_after_costs_percent=5.0,
            sharpe_ratio=1.0,
            max_drawdown_percent=-50.0,
            win_rate=60.0,
            total_trades=10,
        )
        assert result.passes_go_no_go() is False

    def test_to_dict(self) -> None:
        result = BacktestResult(
            backtest_id="bt-001",
            wallet_address="Wallet111111111111111111111111111111111111111",
            strategy_config=StrategyConfig(),
            period_start="2026-01-01",
            period_end="2026-01-02",
            total_trades=5,
        )
        d = result.to_dict()
        assert d["backtest_id"] == "bt-001"
        assert "strategy_config" in d
