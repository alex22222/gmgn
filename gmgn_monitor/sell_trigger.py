from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .portfolio_tracker import PortfolioTracker, Position
from .sell_executor import SellSignal
from .trade_signal import TradeSignal


__all__ = [
    "TriggeredTPState",
    "SellTrigger",
]


@dataclass
class TriggeredTPState:
    """Persistent record of which TP levels have already been triggered for a token."""

    token_address: str
    triggered_levels: set[int] = field(default_factory=set)
    last_updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "token_address": self.token_address,
            "triggered_levels": sorted(self.triggered_levels),
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TriggeredTPState":
        return cls(
            token_address=data.get("token_address", ""),
            triggered_levels=set(data.get("triggered_levels", [])),
            last_updated=data.get("last_updated", datetime.now(timezone.utc).isoformat()),
        )


class SellTrigger:
    """Evaluate open positions against TP/SL thresholds and emit SellSignals.

    Persists triggered TP levels and cached signal configs to JSON files so
    that positions bought in a previous cycle can still be evaluated.
    """

    def __init__(
        self,
        triggered_tp_file: str = "data/triggered_tp.json",
        signal_cache_file: str = "data/signal_cache.json",
    ) -> None:
        self._triggered_tp_file = triggered_tp_file
        self._signal_cache_file = signal_cache_file
        self._triggered_states: dict[str, TriggeredTPState] = {}
        self._signal_cache: dict[str, dict[str, Any]] = {}
        self._load_triggered_tp()
        self._load_signal_cache()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_triggered_tp(self) -> None:
        """Load triggered TP states from the JSON file."""
        if not os.path.exists(self._triggered_tp_file):
            self._triggered_states = {}
            return
        try:
            with open(self._triggered_tp_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for token_addr, state_dict in data.items():
                    if isinstance(state_dict, dict):
                        self._triggered_states[token_addr] = TriggeredTPState.from_dict(state_dict)
        except (json.JSONDecodeError, OSError):
            self._triggered_states = {}

    def _save_triggered_tp(self) -> None:
        """Save triggered TP states to the JSON file."""
        os.makedirs(os.path.dirname(self._triggered_tp_file) or ".", exist_ok=True)
        data = {
            token_addr: state.to_dict()
            for token_addr, state in self._triggered_states.items()
        }
        with open(self._triggered_tp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Signal cache
    # ------------------------------------------------------------------

    def _load_signal_cache(self) -> None:
        """Load cached signal configs from the JSON file."""
        if not os.path.exists(self._signal_cache_file):
            self._signal_cache = {}
            return
        try:
            with open(self._signal_cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._signal_cache = data
        except (json.JSONDecodeError, OSError):
            self._signal_cache = {}

    def _save_signal_cache(self) -> None:
        """Save cached signal configs to the JSON file."""
        os.makedirs(os.path.dirname(self._signal_cache_file) or ".", exist_ok=True)
        with open(self._signal_cache_file, "w", encoding="utf-8") as f:
            json.dump(self._signal_cache, f, indent=2, ensure_ascii=False)

    def save_signal(self, signal: TradeSignal) -> None:
        """Cache a TradeSignal's TP/SL config for later evaluation cycles."""
        self._signal_cache[signal.target_token] = {
            "tp_orders": [
                {
                    "level": tp.level,
                    "trigger_percent": tp.trigger_percent,
                    "sell_percent": tp.sell_percent,
                }
                for tp in signal.tp_orders
            ],
            "sl_order": {
                "trigger_percent": signal.sl_order.trigger_percent,
                "sell_percent": signal.sl_order.sell_percent,
            }
            if signal.sl_order is not None
            else None,
            "max_slippage_percent": signal.max_slippage_percent,
        }
        self._save_signal_cache()

    def remove_signal(self, token_address: str) -> None:
        """Remove a cached signal config (e.g. after full exit)."""
        self._signal_cache.pop(token_address, None)
        self._save_signal_cache()

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate_position(
        self,
        position: Position,
        tp_orders: tuple[Any, ...],
        sl_order: Any | None,
        max_slippage_percent: float = 0.0,
    ) -> SellSignal | None:
        """Evaluate a single position against its TP/SL rules.

        Args:
            position: The open position to evaluate.
            tp_orders: Tuple of TPOrder-like objects (or dicts with
                ``level``, ``trigger_percent``, ``sell_percent``).
            sl_order: SLOrder-like object (or dict) or None.

        Returns:
            A :class:`SellSignal` if a threshold is breached, or ``None``
            if no action is required.
        """
        if position.entry_price_sol <= 0:
            return None

        # Calculate price change percentage
        price_change = (
            (position.current_price_sol - position.entry_price_sol)
            / position.entry_price_sol
            * 100.0
        )

        # a) Check SL first
        if sl_order is not None:
            sl_trigger = (
                sl_order.trigger_percent
                if hasattr(sl_order, "trigger_percent")
                else sl_order.get("trigger_percent", 0.0)
            )
            sl_sell = (
                sl_order.sell_percent
                if hasattr(sl_order, "sell_percent")
                else sl_order.get("sell_percent", 100.0)
            )
            if price_change <= sl_trigger:
                return SellSignal(
                    signal_id=f"sl-{position.token_address}",
                    token_address=position.token_address,
                    sell_percent=sl_sell,
                    trigger_type="SL",
                    trigger_price_usd=None,
                    max_slippage_percent=max_slippage_percent,
                    reason=(
                        f"Stop-loss triggered: price change {price_change:.2f}% "
                        f"<= SL threshold {sl_trigger:.2f}%"
                    ),
                )

        # b) Check TP levels
        if tp_orders:
            # Get or create state for this token
            state = self._triggered_states.get(position.token_address)
            if state is None:
                state = TriggeredTPState(token_address=position.token_address)
                self._triggered_states[position.token_address] = state

            # Sort TP orders by trigger_percent ascending (lowest first)
            def _tp_key(tp: Any) -> float:
                return (
                    tp.trigger_percent
                    if hasattr(tp, "trigger_percent")
                    else tp.get("trigger_percent", float("inf"))
                )

            def _tp_level(tp: Any) -> int:
                return (
                    tp.level
                    if hasattr(tp, "level")
                    else tp.get("level", 0)
                )

            def _tp_sell(tp: Any) -> float:
                return (
                    tp.sell_percent
                    if hasattr(tp, "sell_percent")
                    else tp.get("sell_percent", 0.0)
                )

            def _tp_trigger(tp: Any) -> float:
                return (
                    tp.trigger_percent
                    if hasattr(tp, "trigger_percent")
                    else tp.get("trigger_percent", float("inf"))
                )

            sorted_tp = sorted(tp_orders, key=_tp_key)

            for tp in sorted_tp:
                level = _tp_level(tp)
                # Skip already triggered levels
                if level in state.triggered_levels:
                    continue

                trigger_pct = _tp_trigger(tp)
                if price_change >= trigger_pct:
                    # Mark this level as triggered
                    state.triggered_levels.add(level)
                    state.last_updated = datetime.now(timezone.utc).isoformat()
                    self._save_triggered_tp()

                    return SellSignal(
                        signal_id=f"tp-{level}-{position.token_address}",
                        token_address=position.token_address,
                        sell_percent=_tp_sell(tp),
                        trigger_type="TP",
                        trigger_price_usd=None,
                        max_slippage_percent=max_slippage_percent,
                        reason=(
                            f"Take-profit level {level} triggered: "
                            f"price change {price_change:.2f}% >= "
                            f"TP threshold {trigger_pct:.2f}%"
                        ),
                    )

        return None

    def scan_all_positions(
        self,
        portfolio: PortfolioTracker,
    ) -> list[SellSignal]:
        """Scan all open positions and return any triggered sell signals.

        Uses the internal signal cache so that positions bought in a
        previous cycle can still be evaluated.

        Args:
            portfolio: The portfolio tracker with open positions.

        Returns:
            List of :class:`SellSignal` instances that were triggered.
        """
        sell_signals: list[SellSignal] = []
        for position in portfolio.list_positions():
            cache = self._signal_cache.get(position.token_address)
            if cache is None:
                continue
            tp_orders = tuple(cache.get("tp_orders", []))
            sl_order = cache.get("sl_order")
            sell_signal = self.evaluate_position(
                position, tp_orders, sl_order,
                max_slippage_percent=cache.get("max_slippage_percent", 0.0),
            )
            if sell_signal is not None:
                sell_signals.append(sell_signal)
        return sell_signals

    def reset_triggered_levels(self, token_address: str | None = None) -> None:
        """Reset triggered TP levels for a token (or all tokens if None)."""
        if token_address is None:
            self._triggered_states.clear()
        else:
            self._triggered_states.pop(token_address, None)
        self._save_triggered_tp()
