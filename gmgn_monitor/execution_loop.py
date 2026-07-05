from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from .copy_sell_handler import CopySellHandler
from .css_engine import (
    AccountState,
    CSSDecision,
    CSSEngine,
    CSSResult,
    MarketCondition,
    TimeMomentum,
    TokenRiskScore,
)
from .order_manager import OrderManager
from .portfolio_tracker import PortfolioTracker
from .position_monitor import PositionMonitor
from .risk_manager import RiskCheckResult, RiskManager
from .sell_executor import SellExecutor
from .sell_trigger import SellTrigger
from .signal_preprocessor import SignalPreprocessor
from .trade_signal import TradeSignal


__all__ = [
    "ExecutionLoopEngine",
    "LoopMetrics",
    "MarketData",
]


@dataclass
class MarketData:
    """Helper container for market-level data used during CSS evaluation."""

    token_risk_scores: dict[str, TokenRiskScore] = field(default_factory=dict)
    market_condition: MarketCondition = field(
        default_factory=lambda: MarketCondition(
            btc_trend_24h=0.0,
            overall_sentiment=50.0,
            fear_greed_index=50.0,
        )
    )
    time_momentum: TimeMomentum = field(
        default_factory=lambda: TimeMomentum(
            signal_age_seconds=0.0,
            chain_activity_score=50.0,
            volume_surge_1h=0.0,
        )
    )


@dataclass
class LoopMetrics:
    """Per-cycle metrics capturing the execution pipeline funnel."""

    signals_in: int
    preprocessed_out: int
    css_pass: int
    risk_allow: int
    orders_created: int
    cycle_duration_ms: float
    sell_signals_created: int = 0
    sell_orders_executed: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "signals_in": self.signals_in,
            "preprocessed_out": self.preprocessed_out,
            "css_pass": self.css_pass,
            "risk_allow": self.risk_allow,
            "orders_created": self.orders_created,
            "sell_signals_created": self.sell_signals_created,
            "sell_orders_executed": self.sell_orders_executed,
            "cycle_duration_ms": self.cycle_duration_ms,
            "timestamp": self.timestamp.isoformat(),
        }


class ExecutionLoopEngine:
    """Central orchestrator that wires all Phase 2 modules into a single execution loop.

    The pipeline follows a strict sequential funnel:

    1. **Preprocess** – deduplicate, blacklist, quality-gate.
    2. **CSS Evaluate** – score each signal across five dimensions.
    3. **Filter** – only ``PASS`` signals proceed; ``WATCH`` is logged; ``REJECT`` is dropped.
    4. **Risk Check** – enforce daily loss, position size, and circuit-breaker limits.
    5. **Order Create** – materialise a pending order.
    6. **Portfolio Update** – open the corresponding position.
    """

    def __init__(
        self,
        css_engine: CSSEngine,
        preprocessor: SignalPreprocessor,
        risk_manager: RiskManager,
        order_manager: OrderManager,
        portfolio_tracker: PortfolioTracker,
        market_data: dict | None = None,
        sell_executor: SellExecutor | None = None,
        sell_trigger: SellTrigger | None = None,
        position_monitor: PositionMonitor | None = None,
        copy_sell_handler: CopySellHandler | None = None,
    ) -> None:
        self.css_engine = css_engine
        self.preprocessor = preprocessor
        self.risk_manager = risk_manager
        self.order_manager = order_manager
        self.portfolio_tracker = portfolio_tracker
        self.sell_executor = sell_executor
        self.sell_trigger = sell_trigger
        self.position_monitor = position_monitor
        self.copy_sell_handler = copy_sell_handler
        self._metrics: list[LoopMetrics] = []

        if market_data is None:
            self._market_data = MarketData()
        elif isinstance(market_data, dict):
            self._market_data = MarketData(
                token_risk_scores=market_data.get("token_risk_scores", {}),
                market_condition=market_data.get(
                    "market_condition",
                    MarketCondition(
                        btc_trend_24h=0.0,
                        overall_sentiment=50.0,
                        fear_greed_index=50.0,
                    ),
                ),
                time_momentum=market_data.get(
                    "time_momentum",
                    TimeMomentum(
                        signal_age_seconds=0.0,
                        chain_activity_score=50.0,
                        volume_surge_1h=0.0,
                    ),
                ),
            )
        else:
            self._market_data = MarketData()

    def _make_account_state(self) -> AccountState:
        """Derive an :class:`AccountState` from the current portfolio snapshot."""
        snapshot = self.portfolio_tracker.get_snapshot()
        total_value = snapshot.total_value_sol
        if total_value > 0:
            daily_loss_limit_sol = total_value * (
                self.risk_manager.risk_limits.daily_loss_limit_percent / 100.0
            )
        else:
            daily_loss_limit_sol = 1.0
        return AccountState(
            balance_sol=snapshot.available_sol,
            open_positions_count=len(snapshot.positions),
            daily_pnl_sol=snapshot.daily_pnl_sol,
            daily_loss_limit_sol=max(1.0, daily_loss_limit_sol),
            max_positions=self.risk_manager.risk_limits.max_total_positions,
        )

    def _make_time_momentum(self, signal: TradeSignal) -> TimeMomentum:
        """Build a per-signal :class:`TimeMomentum` using the signal's age."""
        base = self._market_data.time_momentum
        if signal.received_at is not None:
            age_seconds = (datetime.utcnow() - signal.received_at).total_seconds()
        else:
            age_seconds = 0.0
        return TimeMomentum(
            signal_age_seconds=age_seconds,
            chain_activity_score=base.chain_activity_score,
            volume_surge_1h=base.volume_surge_1h,
        )

    def run_cycle(
        self,
        signals: list[TradeSignal],
        wallet_scores: dict[str, float],
    ) -> dict[str, Any]:
        """Execute one full execution cycle.

        Returns a dict with pipeline counts, created orders, and a step-by-step
        execution log.
        """
        start = perf_counter()
        execution_log: list[dict[str, Any]] = []

        # ------------------------------------------------------------------
        # a. Preprocess
        # ------------------------------------------------------------------
        preprocess_result = self.preprocessor.process(signals, wallet_scores)
        accepted_signals = preprocess_result.accepted
        execution_log.append(
            {
                "step": "preprocess",
                "processed_count": len(signals),
                "accepted_count": len(accepted_signals),
                "rejected_count": len(preprocess_result.rejected),
                "details": preprocess_result.stats.to_dict(),
            }
        )

        # ------------------------------------------------------------------
        # b. CSS Evaluate
        # ------------------------------------------------------------------
        css_results: list[tuple[TradeSignal, CSSResult]] = []
        for signal in accepted_signals:
            wallet_score = wallet_scores.get(signal.wallet_address, 0.0)
            token_risk = self._market_data.token_risk_scores.get(
                signal.target_token,
                TokenRiskScore(
                    liquidity_score=50.0,
                    contract_safe=True,
                    market_cap_usd=1_000_000.0,
                    holder_count=1_000,
                ),
            )
            account_state = self._make_account_state()
            time_momentum = self._make_time_momentum(signal)
            css_result = self.css_engine.evaluate(
                signal=signal,
                wallet_score=wallet_score,
                token_risk=token_risk,
                market=self._market_data.market_condition,
                account=account_state,
                momentum=time_momentum,
            )
            css_results.append((signal, css_result))

        # ------------------------------------------------------------------
        # c. Filter (PASS / WATCH / REJECT)
        # ------------------------------------------------------------------
        pass_signals: list[TradeSignal] = []
        watch_signals: list[TradeSignal] = []
        reject_signals: list[TradeSignal] = []
        for signal, css_result in css_results:
            if css_result.decision == CSSDecision.PASS:
                pass_signals.append(signal)
            elif css_result.decision == CSSDecision.WATCH:
                watch_signals.append(signal)
            else:
                reject_signals.append(signal)

        execution_log.append(
            {
                "step": "css_evaluate",
                "evaluated_count": len(css_results),
                "pass_count": len(pass_signals),
                "watch_count": len(watch_signals),
                "reject_count": len(reject_signals),
            }
        )

        # ------------------------------------------------------------------
        # d. Risk Check
        # ------------------------------------------------------------------
        buy_signals = [
            signal
            for signal in pass_signals
            if signal.signal_type in ("NEW_POSITION", "ADD_POSITION")
        ]
        risk_allowed_signals: list[TradeSignal] = []
        for signal in buy_signals:
            snapshot = self.portfolio_tracker.get_snapshot()
            risk_result = self.risk_manager.check_trade(
                signal=signal,
                current_portfolio_value=snapshot.total_value_sol,
                open_positions=[p.to_dict() for p in snapshot.positions],
            )
            if risk_result == RiskCheckResult.ALLOW:
                risk_allowed_signals.append(signal)

        execution_log.append(
            {
                "step": "risk_check",
                "checked_count": len(buy_signals),
                "allow_count": len(risk_allowed_signals),
                "block_count": len(buy_signals) - len(risk_allowed_signals),
                "sell_only_count": len(pass_signals) - len(buy_signals),
            }
        )

        # ------------------------------------------------------------------
        # e. Order Create + f. Portfolio Update
        # ------------------------------------------------------------------
        orders_created: list[dict[str, Any]] = []
        for signal in risk_allowed_signals:
            order = self.order_manager.create_order(signal)
            # Use entry_price_sol=1.0 and quantity=amount so that the cost
            # equals the recommended_amount_sol in the absence of real price data.
            position = self.portfolio_tracker.open_position(
                token_address=signal.target_token,
                entry_price_sol=1.0,
                quantity=signal.recommended_amount_sol,
            )
            # Cache the signal's TP/SL config for cross-cycle sell evaluation
            if self.sell_trigger is not None:
                self.sell_trigger.save_signal(signal)
            orders_created.append(
                {
                    "order_id": order.order_id,
                    "signal_id": signal.signal_id,
                    "token": signal.target_token,
                    "amount_sol": signal.recommended_amount_sol,
                    "position": position.to_dict(),
                }
            )

        execution_log.append(
            {
                "step": "order_create",
                "orders_created_count": len(orders_created),
                "order_ids": [o["order_id"] for o in orders_created],
            }
        )

        # ------------------------------------------------------------------
        # g. Update position prices
        # ------------------------------------------------------------------
        if self.position_monitor:
            self.position_monitor.update_portfolio_prices(self.portfolio_tracker)

        # ------------------------------------------------------------------
        # h. Copy-sell signal handling (EXIT / REDUCE)
        # ------------------------------------------------------------------
        if self.copy_sell_handler:
            for signal in signals:
                if signal.signal_type in ("EXIT", "REDUCE"):
                    self.copy_sell_handler.handle_signal(signal)

        # ------------------------------------------------------------------
        # i. TP / SL trigger detection
        # ------------------------------------------------------------------
        sell_signals: list[dict[str, Any]] = []
        raw_sell_signals: list[Any] = []
        if self.sell_trigger is not None:
            raw_sell_signals = self.sell_trigger.scan_all_positions(
                self.portfolio_tracker
            )
            sell_signals = [s.to_dict() for s in raw_sell_signals]

        # ------------------------------------------------------------------
        # j. Execute sells
        # ------------------------------------------------------------------
        sell_results: list[dict[str, Any]] = []
        if self.sell_executor is not None:
            for raw_signal in raw_sell_signals:
                result = self.sell_executor.execute_sell(raw_signal)
                sell_results.append(result.to_dict())
                # Clean up cache on full exit
                if result.success and raw_signal.sell_percent >= 99.9:
                    if self.sell_trigger is not None:
                        self.sell_trigger.remove_signal(raw_signal.token_address)

        execution_log.append(
            {
                "step": "sell_execution",
                "sell_signals_count": len(sell_signals),
                "sell_results_count": len(sell_results),
            }
        )

        cycle_duration_ms = (perf_counter() - start) * 1000.0

        metrics = LoopMetrics(
            signals_in=len(signals),
            preprocessed_out=len(accepted_signals),
            css_pass=len(pass_signals),
            risk_allow=len(risk_allowed_signals),
            orders_created=len(orders_created),
            sell_signals_created=len(sell_signals),
            sell_orders_executed=len(sell_results),
            cycle_duration_ms=round(cycle_duration_ms, 2),
        )
        self._metrics.append(metrics)

        return {
            "processed_count": len(signals),
            "accepted_count": len(accepted_signals),
            "css_pass_count": len(pass_signals),
            "risk_allow_count": len(risk_allowed_signals),
            "orders_created": orders_created,
            "sell_signals": sell_signals,
            "sell_results": sell_results,
            "execution_log": execution_log,
            "cycle_duration_ms": round(cycle_duration_ms, 2),
        }

    def get_metrics(self) -> list[LoopMetrics]:
        """Return a shallow copy of the full cycle-metrics history."""
        return self._metrics[:]

    def reset_metrics(self) -> None:
        """Clear the cycle-metrics history."""
        self._metrics.clear()
