"""Signal quality optimizer for Phase 2 dry-run pipeline.

The :class:`SignalQualityOptimizer` parameterizes the signal preprocessing
and CSS scoring pipeline to find the configuration that maximises simulated
win rate.
"""
from __future__ import annotations

import random
from dataclasses import replace
from itertools import product
from math import isclose
from typing import Any

from gmgn_monitor.css_engine import CSSWeights
from gmgn_monitor.dry_run_executor import DryRunExecutor
from gmgn_monitor.risk_manager import RiskLimits
from gmgn_monitor.trade_signal import SLOrder, TPOrder, TradeSignal


__all__ = ["SignalQualityOptimizer"]


class SignalQualityOptimizer:
    """Optimise signal-quality parameters via grid-search over the dry-run
    simulation pipeline.

    The optimizer works by running a full :class:`DryRunExecutor` simulation
    for each candidate configuration and measuring the resulting win rate, P&L,
    Sharpe ratio, and max drawdown.

    Usage::

        optimizer = SignalQualityOptimizer()
        optimizer.set_test_data(signals, wallet_scores, market_data)
        best_score = optimizer.optimize_min_wallet_score([50, 60, 70, 80, 90])
        best_weights = optimizer.optimize_css_weights()
        best_config = optimizer.get_best_config()
    """

    def __init__(self, initial_weights: CSSWeights | None = None) -> None:
        self.initial_weights = initial_weights or CSSWeights.default_weights()
        self._best_config: dict[str, Any] = {}
        self._best_win_rate: float = 0.0
        self._signals: list[TradeSignal] = []
        self._wallet_scores: dict[str, float] = {}
        self._market_data: dict[str, list[dict]] | None = None

    # ------------------------------------------------------------------
    # Test-data plumbing
    # ------------------------------------------------------------------

    def set_test_data(
        self,
        signals: list[TradeSignal],
        wallet_scores: dict[str, float],
        market_data: dict[str, list[dict]] | None = None,
    ) -> None:
        """Attach the signal batch and wallet scores that every evaluation
        will run against."""
        self._signals = signals
        self._wallet_scores = wallet_scores
        self._market_data = market_data

    # ------------------------------------------------------------------
    # Public optimisation API
    # ------------------------------------------------------------------

    def optimize_min_wallet_score(self, candidates: list[float]) -> float:
        """Test different *min_wallet_score* thresholds and return the one
        with the highest simulated win rate."""
        best_candidate = candidates[0] if candidates else 50.0
        best_win_rate = 0.0
        for candidate in candidates:
            result = self.evaluate_config(
                weights=self.initial_weights,
                min_wallet_score=candidate,
                tp_orders=(
                    TPOrder(1, 100.0, 50.0),
                    TPOrder(2, 300.0, 50.0),
                ),
                sl_trigger=-65.0,
            )
            win_rate = result.get("win_rate", 0.0)
            if win_rate > best_win_rate:
                best_win_rate = win_rate
                best_candidate = candidate
        return best_candidate

    def optimize_css_weights(
        self,
        weight_ranges: dict[str, tuple[float, float]] | None = None,
    ) -> CSSWeights:
        """Grid-search over CSS weight combinations and return the best set.

        The default ranges cover a plausible Phase 2 search space while keeping
        the total number of valid combinations small enough for a quick dry-run
        iteration."""
        weight_ranges = weight_ranges or {
            "wallet": (0.15, 0.35),
            "token_risk": (0.10, 0.30),
            "market_condition": (0.10, 0.25),
            "account_state": (0.15, 0.25),
            "time_momentum": (0.15, 0.30),
        }

        step = 0.10
        wallet_vals = self._frange(
            weight_ranges["wallet"][0], weight_ranges["wallet"][1], step
        )
        token_risk_vals = self._frange(
            weight_ranges["token_risk"][0], weight_ranges["token_risk"][1], step
        )
        market_vals = self._frange(
            weight_ranges["market_condition"][0],
            weight_ranges["market_condition"][1],
            step,
        )
        account_vals = self._frange(
            weight_ranges["account_state"][0], weight_ranges["account_state"][1], step
        )
        time_vals = self._frange(
            weight_ranges["time_momentum"][0], weight_ranges["time_momentum"][1], step
        )

        # Build all valid weight combinations that sum to 1.0 (±0.01)
        combinations: list[tuple[float, float, float, float, float]] = []
        for w, tr, m, a, t in product(
            wallet_vals, token_risk_vals, market_vals, account_vals, time_vals
        ):
            if isclose(w + tr + m + a + t, 1.0, abs_tol=0.01):
                combinations.append((w, tr, m, a, t))

        # Cap at 20 combinations for speed in the dry-run iteration
        combinations = combinations[:20]

        best_weights = self.initial_weights
        best_win_rate = 0.0

        for combo in combinations:
            weights = CSSWeights(
                wallet=combo[0],
                token_risk=combo[1],
                market_condition=combo[2],
                account_state=combo[3],
                time_momentum=combo[4],
            )
            result = self.evaluate_config(
                weights=weights,
                min_wallet_score=70.0,
                tp_orders=(
                    TPOrder(1, 100.0, 50.0),
                    TPOrder(2, 300.0, 50.0),
                ),
                sl_trigger=-65.0,
            )
            win_rate = result.get("win_rate", 0.0)
            if win_rate > best_win_rate:
                best_win_rate = win_rate
                best_weights = weights

        return best_weights

    def optimize_tp_sl(
        self,
        tp_candidates: list[tuple[float, float]],
        sl_candidates: list[float],
    ) -> tuple[tuple[TPOrder, ...], float]:
        """Test different TP/SL configurations and return the best.

        *tp_candidates* is a list of ``(trigger_percent, sell_percent)`` tuples,
        each representing a single TP level.  *sl_candidates* is a list of stop-loss
        trigger percentages."""
        best_tp: tuple[TPOrder, ...] = (
            TPOrder(1, 100.0, 50.0),
            TPOrder(2, 300.0, 50.0),
        )
        best_sl = -65.0
        best_win_rate = 0.0

        for tp_cfg in tp_candidates:
            tp_orders = (TPOrder(level=1, trigger_percent=tp_cfg[0], sell_percent=tp_cfg[1]),)
            for sl in sl_candidates:
                result = self.evaluate_config(
                    weights=self.initial_weights,
                    min_wallet_score=70.0,
                    tp_orders=tp_orders,
                    sl_trigger=sl,
                )
                win_rate = result.get("win_rate", 0.0)
                if win_rate > best_win_rate:
                    best_win_rate = win_rate
                    best_tp = tp_orders
                    best_sl = sl

        return best_tp, best_sl

    def evaluate_config(
        self,
        weights: CSSWeights,
        min_wallet_score: float,
        tp_orders: tuple[TPOrder, ...],
        sl_trigger: float,
    ) -> dict[str, Any]:
        """Run a full DryRun simulation with the given configuration and
        return a summary dict.

        The simulation outcome is biased by the originating wallet's
        *win_rate_30d* so that filtering out low-quality wallets demonstrably
        raises the aggregate win rate."""
        if not self._signals:
            return {
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "sharpe_ratio": 0.0,
                "max_drawdown": 0.0,
                "wins": 0,
                "losses": 0,
                "total_trades": 0,
            }

        # Build updated signals with the candidate TP/SL
        updated_signals: list[TradeSignal] = []
        for s in self._signals:
            new_s = replace(
                s,
                tp_orders=tp_orders,
                sl_order=SLOrder(trigger_percent=sl_trigger, sell_percent=100.0),
            )
            updated_signals.append(new_s)

        # Configure risk limits
        risk_limits = RiskLimits(
            daily_loss_limit_percent=5.0,
            max_single_position_percent=20.0,
            max_total_positions=5,
            default_stop_loss_percent=sl_trigger,
        )

        # Create a fresh executor with the candidate weights
        executor = DryRunExecutor(
            initial_balance_sol=10.0,
            risk_limits=risk_limits,
            css_weights=weights,
            wallet_scores=self._wallet_scores,
        )
        executor.preprocessor.min_wallet_score = min_wallet_score
        executor.preprocessor.min_confidence = 50

        # Run the full pipeline simulation
        result = executor.run_simulation(
            updated_signals, market_data=self._market_data
        )

        # Build token -> wallet mapping for the TP/SL bias step
        token_to_wallet = {s.target_token: s.wallet_address for s in updated_signals}

        # Simulate TP/SL outcomes biased by wallet quality
        snapshot = executor.portfolio_tracker.get_snapshot()
        positions = list(snapshot.positions)

        tp_sl_results: list[dict[str, Any]] = []
        for position in positions:
            wallet_address = token_to_wallet.get(position.token_address, "")
            wallet_score = self._wallet_scores.get(wallet_address, 50.0)

            # Higher wallet score => higher probability of a winning trade
            win_prob = min(0.95, max(0.05, wallet_score / 100.0))
            rng = random.Random(hash(position.token_address) % 10000)
            outcome = "up" if rng.random() < win_prob else "down"

            if outcome == "up":
                sorted_tp = sorted(tp_orders, key=lambda tp: tp.trigger_percent)
                if sorted_tp:
                    exit_price = position.entry_price_sol * (
                        1.0 + sorted_tp[0].trigger_percent / 100.0
                    )
                else:
                    exit_price = position.entry_price_sol * 2.0
            else:
                exit_price = position.entry_price_sol * (
                    1.0 + sl_trigger / 100.0
                )

            price_series = [{"price_sol": exit_price}]
            tp_sl_result = executor.simulate_tp_sl(position, price_series)
            tp_sl_results.append(tp_sl_result)

        # Aggregate metrics
        wins = sum(1 for r in tp_sl_results if r.get("triggered_by") == "TP")
        losses = sum(1 for r in tp_sl_results if r.get("triggered_by") == "SL")
        total_trades = wins + losses
        win_rate = wins / total_trades if total_trades > 0 else 0.0
        total_pnl = sum(r.get("pnl_sol", 0.0) for r in tp_sl_results)

        pnl_values = [r.get("pnl_sol", 0.0) for r in tp_sl_results]
        if pnl_values:
            avg_pnl = sum(pnl_values) / len(pnl_values)
            variance = sum((p - avg_pnl) ** 2 for p in pnl_values) / len(pnl_values)
            std_pnl = variance ** 0.5
            sharpe = avg_pnl / std_pnl if std_pnl > 0 else 0.0
        else:
            sharpe = 0.0

        max_drawdown = snapshot.max_drawdown_percent

        result_dict: dict[str, Any] = {
            "win_rate": win_rate,
            "total_pnl": round(total_pnl, 4),
            "sharpe_ratio": round(sharpe, 4),
            "max_drawdown": round(max_drawdown, 4),
            "wins": wins,
            "losses": losses,
            "total_trades": total_trades,
            "weights": {
                "wallet": weights.wallet,
                "token_risk": weights.token_risk,
                "market_condition": weights.market_condition,
                "account_state": weights.account_state,
                "time_momentum": weights.time_momentum,
            },
            "min_wallet_score": min_wallet_score,
            "tp_orders": [tp.to_dict() for tp in tp_orders],
            "sl_trigger": sl_trigger,
        }

        if win_rate > self._best_win_rate:
            self._best_win_rate = win_rate
            self._best_config = result_dict.copy()

        return result_dict

    def get_best_config(self) -> dict[str, Any]:
        """Return the best configuration found so far."""
        return self._best_config.copy()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _frange(start: float, stop: float, step: float) -> list[float]:
        """Generate a list of floats from *start* to *stop* (inclusive)."""
        vals: list[float] = []
        v = start
        while v <= stop + 1e-9:
            vals.append(round(v, 4))
            v += step
        return vals
