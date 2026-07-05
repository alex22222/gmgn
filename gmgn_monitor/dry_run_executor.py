from __future__ import annotations

import random
from time import perf_counter
from typing import Any
from uuid import uuid4

from .css_engine import CSSEngine, CSSWeights
from .execution_loop import ExecutionLoopEngine
from .order_manager import Order, OrderManager
from .portfolio_tracker import PortfolioTracker, Position
from .risk_manager import RiskManager, RiskLimits
from .signal_preprocessor import SignalPreprocessor
from .trade_signal import SLOrder, TPOrder, TradeExecution, TradeSignal


__all__ = [
    "DryRunExecutor",
]


class DryRunExecutor:
    """Fully simulated trading executor that runs the complete Phase 2 pipeline
    without submitting real on-chain transactions.

    Internally wires :class:`ExecutionLoopEngine` together with all Phase 2
    modules (CSS, preprocessor, risk, order, portfolio) and mocks chain-level
    execution data (slippage, gas, confirmation).
    """

    def __init__(
        self,
        initial_balance_sol: float = 10.0,
        risk_limits: RiskLimits | None = None,
        css_weights: CSSWeights | None = None,
        wallet_scores: dict[str, float] | None = None,
    ) -> None:
        self._initial_balance_sol = initial_balance_sol
        self._risk_limits = risk_limits or RiskLimits(
            daily_loss_limit_percent=5.0,
            max_single_position_percent=20.0,
            max_total_positions=5,
            default_stop_loss_percent=10.0,
        )
        self._css_weights = css_weights or CSSWeights.default_weights()
        self.wallet_scores = wallet_scores or {}

        self.css_engine = CSSEngine(self._css_weights)
        self.preprocessor = SignalPreprocessor()
        self.risk_manager = RiskManager(self._risk_limits)
        self.portfolio_tracker = PortfolioTracker(initial_balance_sol)
        self.order_manager = OrderManager()

        self._execution_records: list[TradeExecution] = []
        self._total_signals = 0
        # token_address -> (tp_orders, sl_order)
        self._token_rules: dict[str, tuple[tuple[TPOrder, ...], SLOrder | None]] = {}

    def run_simulation(
        self,
        signals: list[TradeSignal],
        market_data: dict | None = None,
    ) -> dict[str, Any]:
        """Run a full dry-run simulation over the given signals.

        Returns a dict with order counts, portfolio snapshot, P&L, and
        execution records.
        """
        start = perf_counter()
        self._total_signals += len(signals)

        # Map signal_id -> signal so we can retrieve TP/SL after the loop
        signal_map = {s.signal_id: s for s in signals}

        loop = ExecutionLoopEngine(
            css_engine=self.css_engine,
            preprocessor=self.preprocessor,
            risk_manager=self.risk_manager,
            order_manager=self.order_manager,
            portfolio_tracker=self.portfolio_tracker,
            market_data=market_data,
        )

        cycle_result = loop.run_cycle(signals, self.wallet_scores)

        # Simulate on-chain execution for each created order
        for order_info in cycle_result["orders_created"]:
            order_id = order_info["order_id"]
            order = self.order_manager.get_order(order_id)
            if order is None:
                continue

            # Keep TP/SL rules for this token (used by simulate_tp_sl)
            signal = signal_map.get(order.signal_id)
            if signal:
                self._token_rules[order.token_address] = (
                    signal.tp_orders,
                    signal.sl_order,
                )

            # Simulate chain submission
            tx_hash = f"dryrun-{order_id[:8]}"
            self.order_manager.submit_order(order_id, tx_hash=tx_hash)

            # Simulate execution data (slippage 0.2–0.5 %, gas 0.01–0.05 SOL)
            slippage = random.uniform(0.2, 0.5)
            gas_cost = random.uniform(0.01, 0.05)
            actual_amount = order.amount_sol * (1.0 - slippage / 100.0)

            self.order_manager.confirm_order(
                order_id,
                actual_amount=actual_amount,
                actual_slippage=slippage,
                gas_cost=gas_cost,
            )

            # Update the open position to reflect the *actual* amount after slippage
            position = self.portfolio_tracker.get_position(order.token_address)
            if position is not None:
                position.quantity = actual_amount
                position._update_unrealized()

            # Build execution record
            execution = self.to_execution(order)
            self._execution_records.append(execution)

        snapshot = self.portfolio_tracker.get_snapshot()
        simulation_duration_ms = (perf_counter() - start) * 1000.0

        return {
            "orders_created": len(cycle_result["orders_created"]),
            "orders_confirmed": len(cycle_result["orders_created"]),
            "orders_failed": 0,
            "portfolio_snapshot": snapshot.to_dict(),
            "total_pnl_sol": snapshot.daily_pnl_sol,
            "simulation_duration_ms": round(simulation_duration_ms, 2),
            "execution_records": [e.to_dict() for e in self._execution_records],
        }

    def simulate_tp_sl(
        self,
        position: Position,
        price_series: list[dict],
    ) -> dict[str, Any]:
        """Simulate take-profit and stop-loss triggers over a price series.

        *price_series* is a list of dicts, each containing at least a
        ``price_sol`` (or ``price``) key.  The method returns the first
        trigger encountered (SL checked before TP at each step).
        """
        if not price_series:
            return {
                "token_address": position.token_address,
                "exit_price": position.entry_price_sol,
                "triggered_by": None,
                "pnl_sol": 0.0,
            }

        tp_orders, sl_order = self._token_rules.get(
            position.token_address,
            ((), None),
        )
        sorted_tp = sorted(tp_orders, key=lambda tp: tp.trigger_percent)

        for price_point in price_series:
            price = price_point.get(
                "price_sol",
                price_point.get("price", position.entry_price_sol),
            )

            if position.entry_price_sol == 0.0:
                pct_change = 0.0
            else:
                pct_change = (
                    (price - position.entry_price_sol)
                    / position.entry_price_sol
                    * 100.0
                )

            # Stop-loss takes precedence
            if sl_order is not None and pct_change <= sl_order.trigger_percent:
                pnl = (price - position.entry_price_sol) * position.quantity
                self.portfolio_tracker.close_position(
                    position.token_address, price
                )
                return {
                    "token_address": position.token_address,
                    "exit_price": price,
                    "triggered_by": "SL",
                    "pnl_sol": pnl,
                }

            # Check TP levels in ascending order of trigger_percent
            for tp in sorted_tp:
                if pct_change >= tp.trigger_percent:
                    pnl = (price - position.entry_price_sol) * position.quantity
                    self.portfolio_tracker.close_position(
                        position.token_address, price
                    )
                    return {
                        "token_address": position.token_address,
                        "exit_price": price,
                        "triggered_by": "TP",
                        "pnl_sol": pnl,
                    }

        # No trigger reached – close at the final price in the series
        last_price = price_series[-1].get(
            "price_sol",
            price_series[-1].get("price", position.entry_price_sol),
        )
        pnl = (last_price - position.entry_price_sol) * position.quantity
        self.portfolio_tracker.close_position(
            position.token_address, last_price
        )
        return {
            "token_address": position.token_address,
            "exit_price": last_price,
            "triggered_by": None,
            "pnl_sol": pnl,
        }

    def get_summary(self) -> dict[str, Any]:
        """Return an aggregate simulation summary."""
        snapshot = self.portfolio_tracker.get_snapshot()
        total_trades = snapshot.win_count + snapshot.loss_count
        win_rate = snapshot.win_count / total_trades if total_trades > 0 else 0.0
        return {
            "total_signals": self._total_signals,
            "total_trades": total_trades,
            "win_rate": win_rate,
            "total_pnl_sol": snapshot.daily_pnl_sol,
            "max_drawdown_percent": snapshot.max_drawdown_percent,
            "sharpe_ratio": snapshot.sharpe_ratio,
        }

    def reset(self) -> None:
        """Clear all internal state and restart with the initial balance."""
        self.portfolio_tracker = PortfolioTracker(self._initial_balance_sol)
        self.order_manager = OrderManager()
        self.risk_manager = RiskManager(self._risk_limits)
        self.css_engine = CSSEngine(self._css_weights)
        self.preprocessor = SignalPreprocessor()
        self._execution_records.clear()
        self._total_signals = 0
        self._token_rules.clear()

    def to_execution(self, order: Order) -> TradeExecution:
        """Convert a confirmed :class:`Order` into a simulated
        :class:`TradeExecution` with mock chain-level data.
        """
        # Slippage 0.2–0.5 % (realistic "slightly less" than recommended)
        slippage = random.uniform(0.2, 0.5)
        gas_cost = random.uniform(0.01, 0.05)
        actual_amount = order.amount_sol * (1.0 - slippage / 100.0)

        return TradeExecution(
            execution_id=str(uuid4()),
            signal_id=order.signal_id,
            status=order.status,
            tx_hash=order.tx_hash,
            actual_amount_sol=actual_amount,
            actual_slippage_percent=slippage,
            gas_cost_sol=gas_cost,
            dry_run=True,
            received_at=order.created_at,
            submitted_at=order.submitted_at,
            confirmed_at=order.confirmed_at,
        )
