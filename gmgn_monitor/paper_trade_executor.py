"""Paper (shadow) trade executors — no chain submission, portfolio-only fills."""
from __future__ import annotations

import random
from dataclasses import dataclass
from time import perf_counter
from typing import Any
from uuid import uuid4

from .portfolio_tracker import PortfolioTracker
from .real_trade_executor import ExecutionResult
from .sell_executor import SellExecutionResult, SellSignal
from .trade_signal import TradeExecution, TradeSignal


__all__ = [
    "PaperBuyExecutor",
    "PaperSellExecutor",
]


@dataclass
class PaperBuyExecutor:
    """Simulate buy fills against a shared portfolio tracker."""

    portfolio: PortfolioTracker
    slippage_min_percent: float = 0.2
    slippage_max_percent: float = 0.8

    # Compatibility with RealTradeExecutor portfolio sync helpers.
    @property
    def _portfolio(self) -> PortfolioTracker:
        return self.portfolio

    @_portfolio.setter
    def _portfolio(self, value: PortfolioTracker) -> None:
        self.portfolio = value

    def execute_trade(self, signal: TradeSignal) -> ExecutionResult:
        start = perf_counter()
        amount = float(signal.recommended_amount_sol or 0.0)
        if amount <= 0:
            return ExecutionResult(
                success=False,
                trade_execution=None,
                order_id=None,
                tx_hash=None,
                error_message="paper buy amount must be > 0",
                gas_cost_sol=0.0,
                actual_slippage_percent=0.0,
                confirmation_time_ms=0.0,
            )

        slippage = random.uniform(self.slippage_min_percent, self.slippage_max_percent)
        fill_amount = amount * (1.0 - slippage / 100.0)
        # Use 1 SOL quote notional as unit price so quantity ~= fill amount in SOL terms.
        entry_price = 1.0
        quantity = fill_amount / entry_price
        order_id = f"paper-buy-{uuid4().hex[:12]}"
        tx_hash = f"paper-{order_id}"

        try:
            existing = self.portfolio.get_position(signal.target_token)
            if existing is None:
                self.portfolio.open_position(
                    signal.target_token,
                    entry_price_sol=entry_price,
                    quantity=quantity,
                )
            # If the execution loop already opened a tentative position, treat
            # this as a successful paper fill confirmation.
        except Exception as exc:
            return ExecutionResult(
                success=False,
                trade_execution=None,
                order_id=order_id,
                tx_hash=None,
                error_message=str(exc),
                gas_cost_sol=0.0,
                actual_slippage_percent=slippage,
                confirmation_time_ms=(perf_counter() - start) * 1000.0,
            )

        execution = TradeExecution(
            execution_id=str(uuid4()),
            signal_id=signal.signal_id,
            status="CONFIRMED",
            tx_hash=tx_hash,
            actual_amount_sol=fill_amount,
            actual_slippage_percent=slippage,
            gas_cost_sol=0.001,
            dry_run=True,
        )
        return ExecutionResult(
            success=True,
            trade_execution=execution,
            order_id=order_id,
            tx_hash=tx_hash,
            error_message=None,
            gas_cost_sol=0.001,
            actual_slippage_percent=slippage,
            confirmation_time_ms=(perf_counter() - start) * 1000.0,
        )


@dataclass
class PaperSellExecutor:
    """Simulate sell fills against a shared portfolio tracker."""

    portfolio: PortfolioTracker
    slippage_min_percent: float = 0.2
    slippage_max_percent: float = 0.8

    def execute_sell(self, signal: SellSignal) -> SellExecutionResult:
        start = perf_counter()
        position = self.portfolio.get_position(signal.token_address)
        if position is None:
            return SellExecutionResult(
                success=False,
                sell_execution=None,
                order_id=None,
                tx_hash=None,
                error_message="paper sell: no open position",
                gas_cost_sol=0.0,
                actual_slippage_percent=0.0,
                confirmation_time_ms=0.0,
            )

        sell_percent = float(getattr(signal, "sell_percent", 100.0) or 100.0)
        slippage = random.uniform(self.slippage_min_percent, self.slippage_max_percent)
        exit_price = float(position.current_price_sol or position.entry_price_sol or 1.0)
        exit_price *= 1.0 - slippage / 100.0
        order_id = f"paper-sell-{uuid4().hex[:12]}"
        tx_hash = f"paper-{order_id}"

        try:
            if sell_percent >= 99.9:
                self.portfolio.close_position(signal.token_address, exit_price)
            else:
                self.portfolio.reduce_position(
                    signal.token_address,
                    quantity=position.quantity * (sell_percent / 100.0),
                    current_price_sol=exit_price,
                )
        except Exception as exc:
            return SellExecutionResult(
                success=False,
                sell_execution=None,
                order_id=order_id,
                tx_hash=None,
                error_message=str(exc),
                gas_cost_sol=0.0,
                actual_slippage_percent=slippage,
                confirmation_time_ms=(perf_counter() - start) * 1000.0,
            )

        return SellExecutionResult(
            success=True,
            sell_execution={
                "execution_id": str(uuid4()),
                "signal_id": getattr(signal, "signal_id", ""),
                "status": "CONFIRMED",
                "tx_hash": tx_hash,
                "dry_run": True,
                "token_address": signal.token_address,
                "sell_percent": sell_percent,
                "exit_price_sol": exit_price,
            },
            order_id=order_id,
            tx_hash=tx_hash,
            error_message=None,
            gas_cost_sol=0.001,
            actual_slippage_percent=slippage,
            confirmation_time_ms=(perf_counter() - start) * 1000.0,
        )
