from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import Enum
from math import isfinite, sqrt
from pathlib import Path
from typing import Any, Iterator

from .serialization import load_json


class BuyMode(Enum):
    """Three supported paper-trading entry modes.

    All modes are *simulated only* — no actual on-chain execution is ever
    performed in Phase 1.
    """

    FIXED_BUY = "fixed_buy"
    MAX_BUY = "max_buy"
    FIXED_RATIO = "fixed_ratio"


class TradeStatus(Enum):
    """Lifecycle states of a single paper trade."""

    OPEN = "open"
    CLOSED = "closed"
    STOPPED = "stopped"
    LIQUIDATED = "liquidated"


class CloseReason(Enum):
    """Reason why a trade was closed."""

    TP_50 = "tp_50"
    TP_100 = "tp_100"
    SL = "sl"
    MANUAL = "manual"
    EXPIRED = "expired"
    LIQUIDATED = "liquidated"


@dataclass(frozen=True)
class TPLevel:
    """Take-profit level configuration and execution state."""

    level: int
    trigger_percent: float
    sell_percent: float
    executed: bool = False
    executed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "trigger_percent": self.trigger_percent,
            "sell_percent": self.sell_percent,
            "executed": self.executed,
            "executed_at": self.executed_at,
        }


@dataclass(frozen=True)
class SLLevel:
    """Stop-loss configuration and execution state."""

    trigger_percent: float
    sell_percent: float = 100.0
    executed: bool = False
    executed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger_percent": self.trigger_percent,
            "sell_percent": self.sell_percent,
            "executed": self.executed,
            "executed_at": self.executed_at,
        }


@dataclass(frozen=True)
class StrategyConfig:
    """Immutable snapshot of the strategy parameters used for a backtest run.

    Defaults mirror the conservative settings from the spec.
    """

    buy_mode: BuyMode = BuyMode.FIXED_BUY
    fixed_sol_amount: float = 0.5
    fixed_ratio: float = 0.1
    sol_price_usd: float = 150.0
    trading_fee_percent: float = 1.0
    slippage_percent: float = 25.0
    priority_fee_sol: float = 0.02
    max_holding_days: int = 7
    tp_levels: tuple[TPLevel, ...] = (
        TPLevel(level=1, trigger_percent=100.0, sell_percent=50.0),
        TPLevel(level=2, trigger_percent=300.0, sell_percent=50.0),
    )
    sl_level: SLLevel = field(default_factory=lambda: SLLevel(trigger_percent=-65.0))

    def to_dict(self) -> dict[str, Any]:
        return {
            "buy_mode": self.buy_mode.value,
            "fixed_sol_amount": self.fixed_sol_amount,
            "fixed_ratio": self.fixed_ratio,
            "sol_price_usd": self.sol_price_usd,
            "trading_fee_percent": self.trading_fee_percent,
            "slippage_percent": self.slippage_percent,
            "priority_fee_sol": self.priority_fee_sol,
            "max_holding_days": self.max_holding_days,
            "tp_levels": [tp.to_dict() for tp in self.tp_levels],
            "sl_level": self.sl_level.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StrategyConfig":
        raw_tp = data.get("tp_levels", [])
        tp_levels = tuple(
            TPLevel(
                level=tp.get("level", 1),
                trigger_percent=tp.get("trigger_percent", 100.0),
                sell_percent=tp.get("sell_percent", 50.0),
            )
            for tp in raw_tp
        )
        raw_sl = data.get("sl_level", {"trigger_percent": -65.0})
        sl_level = SLLevel(
            trigger_percent=raw_sl.get("trigger_percent", -65.0),
            sell_percent=raw_sl.get("sell_percent", 100.0),
        )
        return cls(
            buy_mode=BuyMode(data.get("buy_mode", "fixed_buy")),
            fixed_sol_amount=float(data.get("fixed_sol_amount", 0.5)),
            fixed_ratio=float(data.get("fixed_ratio", 0.1)),
            sol_price_usd=float(data.get("sol_price_usd", 150.0)),
            trading_fee_percent=float(data.get("trading_fee_percent", 1.0)),
            slippage_percent=float(data.get("slippage_percent", 25.0)),
            priority_fee_sol=float(data.get("priority_fee_sol", 0.02)),
            max_holding_days=int(data.get("max_holding_days", 7)),
            tp_levels=tp_levels,
            sl_level=sl_level,
        )


@dataclass(frozen=True)
class PaperTrade:
    """A single paper-trade record.

    All monetary fields are in USD unless suffixed with *_sol*.
    """

    trade_id: str
    wallet_address: str
    token_address: str
    token_symbol: str
    follow_mode: BuyMode
    entry_price: float
    entry_amount_usd: float
    entry_amount_sol: float
    entry_at: str
    exit_price: float | None = None
    exit_amount_usd: float | None = None
    exit_at: str | None = None
    pnl_percent: float | None = None
    pnl_after_costs_percent: float | None = None
    realized_pnl_usd: float | None = None
    holding_duration_minutes: float | None = None
    status: TradeStatus = TradeStatus.OPEN
    close_reason: CloseReason | None = None
    fees_usd: float = 0.0
    slippage_percent: float = 0.0
    priority_fee_sol: float = 0.0
    total_costs_usd: float = 0.0
    tp_levels: tuple[TPLevel, ...] = ()
    sl_level: SLLevel | None = None
    backtest_batch_id: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        _follow = self.follow_mode.value if isinstance(self.follow_mode, Enum) else self.follow_mode
        _status = self.status.value if isinstance(self.status, Enum) else self.status
        _reason = self.close_reason.value if isinstance(self.close_reason, Enum) else self.close_reason
        return {
            "trade_id": self.trade_id,
            "wallet_address": self.wallet_address,
            "token_address": self.token_address,
            "token_symbol": self.token_symbol,
            "follow_mode": _follow,
            "entry_price": self.entry_price,
            "entry_amount_usd": self.entry_amount_usd,
            "entry_amount_sol": self.entry_amount_sol,
            "entry_at": self.entry_at,
            "exit_price": self.exit_price,
            "exit_amount_usd": self.exit_amount_usd,
            "exit_at": self.exit_at,
            "pnl_percent": self.pnl_percent,
            "pnl_after_costs_percent": self.pnl_after_costs_percent,
            "realized_pnl_usd": self.realized_pnl_usd,
            "holding_duration_minutes": self.holding_duration_minutes,
            "status": _status,
            "close_reason": _reason,
            "fees_usd": self.fees_usd,
            "slippage_percent": self.slippage_percent,
            "priority_fee_sol": self.priority_fee_sol,
            "total_costs_usd": self.total_costs_usd,
            "tp_levels": [tp.to_dict() for tp in self.tp_levels],
            "sl_level": self.sl_level.to_dict() if self.sl_level else None,
            "backtest_batch_id": self.backtest_batch_id,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class CostModel:
    """Conservative cost model for Solana meme-token trading.

    Fees are applied *twice* (entry + exit) because every round-trip pays
    trading fees, slippage, and priority fees on both sides.
    """

    trading_fee_percent: float = 1.0
    slippage_percent: float = 25.0
    priority_fee_sol: float = 0.02
    sol_price_usd: float = 150.0

    def entry_costs(self, amount_usd: float) -> dict[str, float]:
        """Return costs paid on the entry side only."""
        fee = amount_usd * self.trading_fee_percent / 100.0
        slippage = amount_usd * self.slippage_percent / 100.0
        priority_fee_usd = self.priority_fee_sol * self.sol_price_usd
        return {
            "fee_usd": fee,
            "slippage_usd": slippage,
            "priority_fee_usd": priority_fee_usd,
            "total_costs_usd": fee + slippage + priority_fee_usd,
        }

    def exit_costs(self, amount_usd: float) -> dict[str, float]:
        """Exit costs are symmetric to entry costs."""
        return self.entry_costs(amount_usd)

    def round_trip_costs(self, entry_amount_usd: float, exit_amount_usd: float) -> dict[str, float]:
        """Sum entry + exit costs for a complete trade."""
        entry = self.entry_costs(entry_amount_usd)
        exit = self.exit_costs(exit_amount_usd)
        return {
            "fee_usd": entry["fee_usd"] + exit["fee_usd"],
            "slippage_usd": entry["slippage_usd"] + exit["slippage_usd"],
            "priority_fee_usd": entry["priority_fee_usd"] + exit["priority_fee_usd"],
            "total_costs_usd": entry["total_costs_usd"] + exit["total_costs_usd"],
        }


@dataclass(frozen=True)
class BacktestResult:
    """Aggregated result of a single backtest run."""

    backtest_id: str
    wallet_address: str
    strategy_config: StrategyConfig
    period_start: str
    period_end: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_return_percent: float = 0.0
    annualized_return_percent: float = 0.0
    max_drawdown_percent: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    avg_holding_duration_hours: float = 0.0
    expectancy_per_trade_percent: float = 0.0
    expectancy_after_costs_percent: float = 0.0
    total_fees_usd: float = 0.0
    total_slippage_usd: float = 0.0
    total_priority_fees_usd: float = 0.0
    total_costs_percent: float = 0.0
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    daily_returns: list[dict[str, Any]] = field(default_factory=list)
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "backtest_id": self.backtest_id,
            "wallet_address": self.wallet_address,
            "strategy_config": self.strategy_config.to_dict(),
            "period_start": self.period_start,
            "period_end": self.period_end,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "total_return_percent": self.total_return_percent,
            "annualized_return_percent": self.annualized_return_percent,
            "max_drawdown_percent": self.max_drawdown_percent,
            "sharpe_ratio": self.sharpe_ratio,
            "sortino_ratio": self.sortino_ratio,
            "avg_holding_duration_hours": self.avg_holding_duration_hours,
            "expectancy_per_trade_percent": self.expectancy_per_trade_percent,
            "expectancy_after_costs_percent": self.expectancy_after_costs_percent,
            "total_fees_usd": self.total_fees_usd,
            "total_slippage_usd": self.total_slippage_usd,
            "total_priority_fees_usd": self.total_priority_fees_usd,
            "total_costs_percent": self.total_costs_percent,
            "equity_curve": self.equity_curve,
            "daily_returns": self.daily_returns,
            "generated_at": self.generated_at,
        }

    def is_positive_expectancy(self) -> bool:
        """Return True if the strategy shows positive expectancy after costs."""
        return self.expectancy_after_costs_percent > 0

    def passes_go_no_go(self, min_sharpe: float = 0.5, max_drawdown: float = -40.0, min_win_rate: float = 55.0) -> bool:
        """Phase-1 Go/No-Go gate for a single backtest result."""
        if not self.is_positive_expectancy():
            return False
        if self.sharpe_ratio < min_sharpe:
            return False
        if self.max_drawdown_percent < max_drawdown:
            return False
        if self.win_rate < min_win_rate:
            return False
        return True


class TradeLifecycle:
    """Mutable state machine that manages a single PaperTrade from entry to exit.

    *Not* frozen — it tracks the evolving position as price updates arrive.
    """

    def __init__(self, paper_trade: PaperTrade) -> None:
        self.trade = paper_trade
        self.remaining_position = 100.0
        self.status = TradeStatus.OPEN
        self._closed_tp_levels: set[int] = set()

    def update_price(self, current_price: float, current_time: str) -> None:
        """Evaluate TP/SL triggers against *current_price*.

        Idempotent: once the trade is no longer OPEN, subsequent calls are no-ops.
        """
        if self.status != TradeStatus.OPEN:
            return

        if self.trade.entry_price == 0:
            return

        pnl_percent = (current_price - self.trade.entry_price) / self.trade.entry_price * 100.0

        # Check full liquidation before SL (price=0 is a special case)
        if current_price <= 0 and self.remaining_position > 0:
            self._execute_liquidation(current_price, current_time)
            return

        # Evaluate TP levels in order
        for tp in self.trade.tp_levels:
            if tp.level not in self._closed_tp_levels and pnl_percent >= tp.trigger_percent:
                self._execute_tp(tp, current_price, current_time)

        # Evaluate SL (full position)
        if self.trade.sl_level and self.remaining_position > 0:
            if pnl_percent <= self.trade.sl_level.trigger_percent:
                self._execute_sl(current_price, current_time)

        # Expiry check
        if self.remaining_position > 0 and self._is_expired(current_time):
            self._execute_expiry(current_price, current_time)

    def _execute_tp(self, tp: TPLevel, price: float, time: str) -> None:
        self._closed_tp_levels.add(tp.level)
        self.remaining_position -= tp.sell_percent
        if self.remaining_position <= 0:
            self.status = TradeStatus.CLOSED
            self.trade = self._replace_trade(
                exit_price=price,
                exit_at=time,
                close_reason=CloseReason.TP_50 if tp.level == 1 else CloseReason.TP_100,
                status=TradeStatus.CLOSED,
            )

    def _execute_sl(self, price: float, time: str) -> None:
        self.remaining_position = 0.0
        self.status = TradeStatus.STOPPED
        self.trade = self._replace_trade(
            exit_price=price,
            exit_at=time,
            close_reason=CloseReason.SL,
            status=TradeStatus.STOPPED,
        )

    def _execute_liquidation(self, price: float, time: str) -> None:
        self.remaining_position = 0.0
        self.status = TradeStatus.LIQUIDATED
        self.trade = self._replace_trade(
            exit_price=price,
            exit_at=time,
            close_reason=CloseReason.LIQUIDATED,
            status=TradeStatus.LIQUIDATED,
        )

    def _execute_expiry(self, price: float, time: str) -> None:
        self.remaining_position = 0.0
        self.status = TradeStatus.CLOSED
        self.trade = self._replace_trade(
            exit_price=price,
            exit_at=time,
            close_reason=CloseReason.EXPIRED,
            status=TradeStatus.CLOSED,
        )

    def _is_expired(self, current_time: str) -> bool:
        try:
            entry = datetime.fromisoformat(self.trade.entry_at.replace("Z", "+00:00"))
            now = datetime.fromisoformat(current_time.replace("Z", "+00:00"))
        except ValueError:
            return False
        max_hold = timedelta(days=self.trade.tp_levels[0].trigger_percent if self.trade.tp_levels else 7)
        # Use max_holding_days from a sensible default if we cannot infer it
        max_days = 7
        return (now - entry) > timedelta(days=max_days)

    def _replace_trade(self, **kwargs: Any) -> PaperTrade:
        # Build a new PaperTrade from the current one, overriding with kwargs
        d = self.trade.to_dict()
        for key, value in kwargs.items():
            if isinstance(value, Enum):
                d[key] = value.value
            else:
                d[key] = value
        # Reconstruct nested dataclass fields from dicts (to_dict flattens them)
        if "tp_levels" in d and d["tp_levels"]:
            d["tp_levels"] = tuple(
                TPLevel(**tp) if isinstance(tp, dict) else tp for tp in d["tp_levels"]
            )
        if "sl_level" in d and d["sl_level"] is not None:
            if isinstance(d["sl_level"], dict):
                d["sl_level"] = SLLevel(**d["sl_level"])
        if "follow_mode" in d and isinstance(d["follow_mode"], str):
            d["follow_mode"] = BuyMode(d["follow_mode"])
        if "status" in d and isinstance(d["status"], str):
            d["status"] = TradeStatus(d["status"])
        if "close_reason" in d and d["close_reason"] is not None and isinstance(d["close_reason"], str):
            d["close_reason"] = CloseReason(d["close_reason"])
        return PaperTrade(**d)

    def finalize(self, cost_model: CostModel) -> PaperTrade:
        """Compute PnL, costs, and holding duration after the trade is closed.

        Must be called *after* the last price update (or after expiry/liquidation).
        """
        trade = self.trade
        if trade.exit_price is None or trade.exit_at is None:
            return trade

        # Raw PnL before costs
        pnl_percent = (trade.exit_price - trade.entry_price) / trade.entry_price * 100.0
        realized_pnl_usd = trade.entry_amount_usd * (pnl_percent / 100.0)

        # Costs
        exit_notional = trade.entry_amount_usd + realized_pnl_usd
        costs = cost_model.round_trip_costs(trade.entry_amount_usd, exit_notional)
        total_costs = costs["total_costs_usd"]
        pnl_after_costs = realized_pnl_usd - total_costs
        pnl_after_costs_percent = (pnl_after_costs / trade.entry_amount_usd) * 100.0 if trade.entry_amount_usd else 0.0

        # Holding duration
        try:
            entry_dt = datetime.fromisoformat(trade.entry_at.replace("Z", "+00:00"))
            exit_dt = datetime.fromisoformat(trade.exit_at.replace("Z", "+00:00"))
            holding_minutes = (exit_dt - entry_dt).total_seconds() / 60.0
        except ValueError:
            holding_minutes = 0.0

        self.trade = replace(
            trade,
            pnl_percent=round(pnl_percent, 4),
            pnl_after_costs_percent=round(pnl_after_costs_percent, 4),
            realized_pnl_usd=round(realized_pnl_usd, 4),
            fees_usd=round(costs["fee_usd"], 4),
            slippage_percent=cost_model.slippage_percent,
            priority_fee_sol=cost_model.priority_fee_sol,
            total_costs_usd=round(total_costs, 4),
            holding_duration_minutes=round(holding_minutes, 4),
        )
        return self.trade


@dataclass(frozen=True)
class WalkForwardWindow:
    """A single train/test split used in Walk-Forward validation."""

    train_start: str
    train_end: str
    test_start: str
    test_end: str
    params: dict[str, Any] = field(default_factory=dict)
    test_result: BacktestResult | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "train_start": self.train_start,
            "train_end": self.train_end,
            "test_start": self.test_start,
            "test_end": self.test_end,
            "params": self.params,
            "test_result": self.test_result.to_dict() if self.test_result else None,
        }


class BacktestEngine:
    """Paper-trading backtest engine with Walk-Forward validation.

    Phase-1 safety boundary: **no on-chain execution**.  All trades are
    simulated locally using the provided price time-series.

    Usage
    -----
    >>> engine = BacktestEngine()
    >>> result = engine.run_backtest(wallet_address, price_data, strategy_config)
    >>> wfo_results = engine.walk_forward(wallet_address, price_data, strategy_config)
    """

    def __init__(self) -> None:
        self.trades: list[PaperTrade] = []

    def run_backtest(
        self,
        wallet_address: str,
        price_data: dict[str, list[dict[str, Any]]],
        strategy_config: StrategyConfig,
        backtest_id: str = "",
    ) -> BacktestResult:
        """Run a single-period backtest over *price_data*.

        *price_data* is a mapping ``token_address -> [{timestamp, price}, ...]``
        sorted chronologically.

        Returns a fully-populated ``BacktestResult``.
        """
        self.trades = []
        cost_model = CostModel(
            trading_fee_percent=strategy_config.trading_fee_percent,
            slippage_percent=strategy_config.slippage_percent,
            priority_fee_sol=strategy_config.priority_fee_sol,
            sol_price_usd=strategy_config.sol_price_usd,
        )

        for token_address, series in price_data.items():
            if not series:
                continue
            # Simulate one entry at the first price and one exit at the last price
            entry_point = series[0]
            exit_point = series[-1]
            paper = self._create_paper_trade(
                wallet_address=wallet_address,
                token_address=token_address,
                token_symbol="UNKNOWN",
                strategy_config=strategy_config,
                entry_price=entry_point["price"],
                entry_at=entry_point["timestamp"],
                backtest_batch_id=backtest_id,
            )
            lifecycle = TradeLifecycle(paper)

            # Walk through the price series, evaluating TP/SL at each step
            for point in series:
                lifecycle.update_price(point["price"], point["timestamp"])
                if lifecycle.status != TradeStatus.OPEN:
                    break

            # If still open at the end, force-close at the final price
            if lifecycle.status == TradeStatus.OPEN:
                lifecycle.update_price(exit_point["price"], exit_point["timestamp"])
                # Expiry/force close
                lifecycle._execute_expiry(exit_point["price"], exit_point["timestamp"])  # type: ignore[misc]

            finalized = lifecycle.finalize(cost_model)
            self.trades.append(finalized)

        return self._aggregate_result(wallet_address, strategy_config, backtest_id, price_data)

    def run_signal_backtest(
        self,
        wallet_address: str,
        signals: list[Any],
        price_data: dict[str, list[dict]],  # {token: [{timestamp, price}, ...]}
        strategy_config: StrategyConfig,
        backtest_id: str = "",
    ) -> BacktestResult:
        """Run backtest following a list of buy signals instead of buying all tokens.

        Each signal triggers a paper trade at the signal's timestamp/price,
        then follows the price series for that token from that point onward.
        """
        self.trades = []
        cost_model = CostModel(
            trading_fee_percent=strategy_config.trading_fee_percent,
            slippage_percent=strategy_config.slippage_percent,
            priority_fee_sol=strategy_config.priority_fee_sol,
            sol_price_usd=strategy_config.sol_price_usd,
        )

        for signal in signals:
            token_series = price_data.get(signal.token_address, [])
            if not token_series:
                continue

            # Find entry point in series
            entry_idx = self._find_timestamp_index(token_series, signal.timestamp)
            if entry_idx is None:
                continue

            entry_point = token_series[entry_idx]
            exit_point = token_series[-1]

            paper = self._create_paper_trade(
                wallet_address=wallet_address,
                token_address=signal.token_address,
                token_symbol="UNKNOWN",
                strategy_config=strategy_config,
                entry_price=signal.price_usd,
                entry_at=signal.timestamp,
                backtest_batch_id=backtest_id,
            )
            lifecycle = TradeLifecycle(paper)

            # Walk through price series from entry point onward
            for point in token_series[entry_idx:]:
                lifecycle.update_price(point["price"], point["timestamp"])
                if lifecycle.status != TradeStatus.OPEN:
                    break

            if lifecycle.status == TradeStatus.OPEN:
                lifecycle.update_price(exit_point["price"], exit_point["timestamp"])
                lifecycle._execute_expiry(exit_point["price"], exit_point["timestamp"])  # type: ignore[misc]

            finalized = lifecycle.finalize(cost_model)
            self.trades.append(finalized)

        # Build synthetic price_data for aggregation from all tokens used
        used_tokens = {s.token_address for s in signals}
        used_price_data = {t: price_data[t] for t in used_tokens if t in price_data}
        return self._aggregate_result(wallet_address, strategy_config, backtest_id, used_price_data)

    def _find_timestamp_index(self, series: list[dict], timestamp: str) -> int | None:
        """Find the index of the closest timestamp in the series."""
        for i, point in enumerate(series):
            if point["timestamp"] >= timestamp:
                return i
        return None if not series else len(series) - 1

    def walk_forward(
        self,
        wallet_address: str,
        price_data: dict[str, list[dict[str, Any]]],
        strategy_config: StrategyConfig,
        train_window_days: int = 14,
        test_window_days: int = 7,
    ) -> list[WalkForwardWindow]:
        """Run Walk-Forward validation with sliding train/test windows.

        Returns one ``WalkForwardWindow`` per split.
        """
        all_timestamps = [
            point["timestamp"]
            for series in price_data.values()
            for point in series
        ]
        if not all_timestamps:
            return []

        # Naive chronological sort (ISO-8601 strings sort lexicographically)
        all_timestamps.sort()
        start = datetime.fromisoformat(all_timestamps[0].replace("Z", "+00:00"))
        end = datetime.fromisoformat(all_timestamps[-1].replace("Z", "+00:00"))

        windows: list[WalkForwardWindow] = []
        current = start
        step = timedelta(days=test_window_days)
        train_delta = timedelta(days=train_window_days)
        test_delta = timedelta(days=test_window_days)

        while current + train_delta + test_delta <= end:
            train_end = current + train_delta
            test_end = train_end + test_delta

            train_data = self._slice_price_data(price_data, current, train_end)
            test_data = self._slice_price_data(price_data, train_end, test_end)

            if not test_data:
                current += step
                continue

            # Training: placeholder for parameter optimisation (here we just pass config)
            train_result = self.run_backtest(wallet_address, train_data, strategy_config, backtest_id=f"wf-train-{len(windows)}")

            # Testing: use same config on the test window
            test_result = self.run_backtest(wallet_address, test_data, strategy_config, backtest_id=f"wf-test-{len(windows)}")

            windows.append(
                WalkForwardWindow(
                    train_start=current.isoformat(),
                    train_end=train_end.isoformat(),
                    test_start=train_end.isoformat(),
                    test_end=test_end.isoformat(),
                    params=strategy_config.to_dict(),
                    test_result=test_result,
                )
            )
            current += step

        return windows

    def compare_strategies(
        self,
        wallet_address: str,
        price_data: dict[str, list[dict[str, Any]]],
        strategies: list[StrategyConfig],
    ) -> list[BacktestResult]:
        """Run the same price data through multiple strategy configs and return ordered results."""
        results = [
            self.run_backtest(wallet_address, price_data, cfg, backtest_id=f"compare-{i}")
            for i, cfg in enumerate(strategies)
        ]
        # Sort: positive expectancy first, then higher Sharpe, then smaller drawdown
        results.sort(
            key=lambda r: (
                r.expectancy_after_costs_percent > 0,
                r.expectancy_after_costs_percent,
                r.sharpe_ratio,
                -abs(r.max_drawdown_percent),
            ),
            reverse=True,
        )
        return results

    def _create_paper_trade(
        self,
        wallet_address: str,
        token_address: str,
        token_symbol: str,
        strategy_config: StrategyConfig,
        entry_price: float,
        entry_at: str,
        backtest_batch_id: str,
    ) -> PaperTrade:
        from uuid import uuid4

        amount_sol = strategy_config.fixed_sol_amount
        amount_usd = amount_sol * strategy_config.sol_price_usd

        return PaperTrade(
            trade_id=str(uuid4()),
            wallet_address=wallet_address,
            token_address=token_address,
            token_symbol=token_symbol,
            follow_mode=strategy_config.buy_mode,
            entry_price=entry_price,
            entry_amount_usd=amount_usd,
            entry_amount_sol=amount_sol,
            entry_at=entry_at,
            tp_levels=strategy_config.tp_levels,
            sl_level=strategy_config.sl_level,
            backtest_batch_id=backtest_batch_id,
            created_at=datetime.now().isoformat(),
        )

    def _slice_price_data(
        self,
        price_data: dict[str, list[dict[str, Any]]],
        start: datetime,
        end: datetime,
    ) -> dict[str, list[dict[str, Any]]]:
        sliced: dict[str, list[dict[str, Any]]] = {}
        for token, series in price_data.items():
            filtered = [
                point for point in series
                if start <= datetime.fromisoformat(point["timestamp"].replace("Z", "+00:00")) < end
            ]
            if filtered:
                sliced[token] = filtered
        return sliced

    def _aggregate_result(
        self,
        wallet_address: str,
        strategy_config: StrategyConfig,
        backtest_id: str,
        price_data: dict[str, list[dict[str, Any]]],
    ) -> BacktestResult:
        all_timestamps = sorted(
            {point["timestamp"] for series in price_data.values() for point in series}
        )
        period_start = all_timestamps[0] if all_timestamps else ""
        period_end = all_timestamps[-1] if all_timestamps else ""

        total_trades = len(self.trades)
        winning_trades = sum(1 for t in self.trades if (t.pnl_after_costs_percent or 0) > 0)
        losing_trades = sum(1 for t in self.trades if (t.pnl_after_costs_percent or 0) <= 0)
        win_rate = (winning_trades / total_trades * 100.0) if total_trades else 0.0

        total_profit = sum((t.pnl_after_costs_percent or 0) for t in self.trades if (t.pnl_after_costs_percent or 0) > 0)
        total_loss = sum(abs(t.pnl_after_costs_percent or 0) for t in self.trades if (t.pnl_after_costs_percent or 0) <= 0)
        profit_factor = (total_profit / total_loss) if total_loss > 0 else float("inf")

        total_return = sum((t.pnl_after_costs_percent or 0) for t in self.trades)
        annualized_return = self._annualize_return(total_return, period_start, period_end)

        max_dd = self._compute_max_drawdown(self.trades)
        sharpe = self._compute_sharpe(self.trades)
        sortino = self._compute_sortino(self.trades)

        avg_hold = sum((t.holding_duration_minutes or 0) for t in self.trades) / total_trades if total_trades else 0.0

        expectancy = total_return / total_trades if total_trades else 0.0
        total_costs = sum(t.total_costs_usd for t in self.trades)
        total_fees = sum(t.fees_usd for t in self.trades)
        total_slippage = sum(t.entry_amount_usd * t.slippage_percent / 100.0 for t in self.trades)
        total_priority = sum(t.priority_fee_sol * strategy_config.sol_price_usd for t in self.trades)
        entry_capital = sum(t.entry_amount_usd for t in self.trades)
        costs_percent = (total_costs / entry_capital * 100.0) if entry_capital else 0.0
        expectancy_after_costs = expectancy - costs_percent

        equity_curve = self._build_equity_curve(self.trades, all_timestamps)
        daily_returns = self._build_daily_returns(self.trades)

        return BacktestResult(
            backtest_id=backtest_id,
            wallet_address=wallet_address,
            strategy_config=strategy_config,
            period_start=period_start,
            period_end=period_end,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=round(win_rate, 2),
            profit_factor=round(profit_factor, 2),
            total_return_percent=round(total_return, 2),
            annualized_return_percent=round(annualized_return, 2),
            max_drawdown_percent=round(max_dd, 2),
            sharpe_ratio=round(sharpe, 2),
            sortino_ratio=round(sortino, 2),
            avg_holding_duration_hours=round(avg_hold / 60.0, 2),
            expectancy_per_trade_percent=round(expectancy, 4),
            expectancy_after_costs_percent=round(expectancy_after_costs, 4),
            total_fees_usd=round(total_fees, 4),
            total_slippage_usd=round(total_slippage, 4),
            total_priority_fees_usd=round(total_priority, 4),
            total_costs_percent=round(costs_percent, 4),
            equity_curve=equity_curve,
            daily_returns=daily_returns,
            generated_at=datetime.now().isoformat(),
        )

    def _annualize_return(self, total_return: float, start: str, end: str) -> float:
        try:
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        except ValueError:
            return 0.0
        days = max((end_dt - start_dt).total_seconds() / 86400.0, 1.0)
        return total_return * (365.0 / days)

    def _compute_max_drawdown(self, trades: list[PaperTrade]) -> float:
        """Compute maximum drawdown from a simple equity curve."""
        if not trades:
            return 0.0
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in trades:
            equity += t.pnl_after_costs_percent or 0.0
            if equity > peak:
                peak = equity
            dd = equity - peak
            if dd < max_dd:
                max_dd = dd
        return max_dd

    def _compute_sharpe(self, trades: list[PaperTrade]) -> float:
        returns = [t.pnl_after_costs_percent or 0.0 for t in trades]
        if not returns or len(returns) < 2:
            return 0.0
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        std = sqrt(variance) if variance > 0 else 0.0
        return (mean / std) if std > 0 else 0.0

    def _compute_sortino(self, trades: list[PaperTrade]) -> float:
        returns = [t.pnl_after_costs_percent or 0.0 for t in trades]
        if not returns or len(returns) < 2:
            return 0.0
        mean = sum(returns) / len(returns)
        downside = [r for r in returns if r < 0]
        if not downside:
            return float("inf") if mean > 0 else 0.0
        downside_var = sum((r - 0) ** 2 for r in downside) / (len(returns) - 1)
        downside_std = sqrt(downside_var) if downside_var > 0 else 0.0
        return (mean / downside_std) if downside_std > 0 else 0.0

    def _build_equity_curve(self, trades: list[PaperTrade], timestamps: list[str]) -> list[dict[str, Any]]:
        equity = 0.0
        curve: list[dict[str, Any]] = []
        for t in trades:
            equity += t.pnl_after_costs_percent or 0.0
            curve.append({"timestamp": t.exit_at or t.entry_at, "equity": round(equity, 4)})
        return curve

    def _build_daily_returns(self, trades: list[PaperTrade]) -> list[dict[str, Any]]:
        daily: dict[str, float] = {}
        for t in trades:
            day = (t.exit_at or t.entry_at)[:10]  # YYYY-MM-DD
            if not day:
                continue
            daily[day] = daily.get(day, 0.0) + (t.pnl_after_costs_percent or 0.0)
        return [{"date": d, "return": round(r, 4)} for d, r in sorted(daily.items())]
