from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

__all__ = [
    "PnLStats",
    "PortfolioSnapshot",
    "PortfolioTracker",
    "Position",
]


@dataclass
class Position:
    """Open position in a single token."""

    token_address: str
    entry_price_sol: float
    current_price_sol: float
    quantity: float
    entry_time: str | None = None
    last_updated: str | None = None
    unrealized_pnl_sol: float = 0.0
    realized_pnl_sol: float = 0.0

    def __post_init__(self) -> None:
        self._update_unrealized()

    def _update_unrealized(self) -> None:
        self.unrealized_pnl_sol = (self.current_price_sol - self.entry_price_sol) * self.quantity

    def to_dict(self) -> dict[str, Any]:
        return {
            "token_address": self.token_address,
            "entry_price_sol": self.entry_price_sol,
            "current_price_sol": self.current_price_sol,
            "quantity": self.quantity,
            "entry_time": self.entry_time,
            "last_updated": self.last_updated,
            "unrealized_pnl_sol": self.unrealized_pnl_sol,
            "realized_pnl_sol": self.realized_pnl_sol,
        }


@dataclass
class PnLStats:
    """Aggregated P&L statistics for a portfolio snapshot."""

    daily_pnl_sol: float
    daily_pnl_percent: float
    total_return_percent: float
    sharpe_ratio: float
    max_drawdown_percent: float
    win_count: int
    loss_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "daily_pnl_sol": self.daily_pnl_sol,
            "daily_pnl_percent": self.daily_pnl_percent,
            "total_return_percent": self.total_return_percent,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown_percent": self.max_drawdown_percent,
            "win_count": self.win_count,
            "loss_count": self.loss_count,
        }


@dataclass
class PortfolioSnapshot:
    """Point-in-time view of the portfolio."""

    timestamp: str
    total_value_sol: float
    available_sol: float
    positions: list[Position]
    daily_pnl_sol: float
    daily_pnl_percent: float
    total_return_percent: float
    sharpe_ratio: float
    max_drawdown_percent: float
    win_count: int
    loss_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "total_value_sol": self.total_value_sol,
            "available_sol": self.available_sol,
            "positions": [p.to_dict() for p in self.positions],
            "daily_pnl_sol": self.daily_pnl_sol,
            "daily_pnl_percent": self.daily_pnl_percent,
            "total_return_percent": self.total_return_percent,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown_percent": self.max_drawdown_percent,
            "win_count": self.win_count,
            "loss_count": self.loss_count,
        }

    def to_pnl_stats(self) -> PnLStats:
        return PnLStats(
            daily_pnl_sol=self.daily_pnl_sol,
            daily_pnl_percent=self.daily_pnl_percent,
            total_return_percent=self.total_return_percent,
            sharpe_ratio=self.sharpe_ratio,
            max_drawdown_percent=self.max_drawdown_percent,
            win_count=self.win_count,
            loss_count=self.loss_count,
        )


class PortfolioTracker:
    """Tracks open positions, computes P&L, and generates portfolio snapshots."""

    def __init__(self, initial_balance_sol: float) -> None:
        self._initial_balance_sol = initial_balance_sol
        self._available_sol = initial_balance_sol
        self._positions: dict[str, Position] = {}
        self._daily_pnl_sol = 0.0
        self._win_count = 0
        self._loss_count = 0
        self._peak_value_sol = initial_balance_sol
        self._max_drawdown_percent = 0.0
        self._daily_returns: list[float] = []
        self._last_daily_value_sol = initial_balance_sol

    def open_position(
        self,
        token_address: str,
        entry_price_sol: float,
        quantity: float,
        entry_time: str | None = None,
    ) -> Position:
        if token_address in self._positions:
            raise ValueError(f"Position already open for token: {token_address}")
        cost = entry_price_sol * quantity
        if cost > self._available_sol:
            raise ValueError(
                f"Insufficient balance: cost {cost:.6f} SOL > available "
                f"{self._available_sol:.6f} SOL"
            )
        self._available_sol -= cost
        if entry_time is None:
            entry_time = datetime.now(timezone.utc).isoformat()
        position = Position(
            token_address=token_address,
            entry_price_sol=entry_price_sol,
            current_price_sol=entry_price_sol,
            quantity=quantity,
            entry_time=entry_time,
            last_updated=entry_time,
            unrealized_pnl_sol=0.0,
            realized_pnl_sol=0.0,
        )
        self._positions[token_address] = position
        return position

    def close_position(
        self,
        token_address: str,
        exit_price_sol: float,
        exit_time: str | None = None,
    ) -> tuple[Position, float]:
        if token_address not in self._positions:
            raise ValueError(f"Position not found for token: {token_address}")
        position = self._positions.pop(token_address)
        realized_pnl = (exit_price_sol - position.entry_price_sol) * position.quantity
        position.realized_pnl_sol = realized_pnl
        position.current_price_sol = exit_price_sol
        position.unrealized_pnl_sol = 0.0
        if exit_time is None:
            exit_time = datetime.now(timezone.utc).isoformat()
        position.last_updated = exit_time
        proceeds = exit_price_sol * position.quantity
        self._available_sol += proceeds
        self._daily_pnl_sol += realized_pnl
        if realized_pnl > 0:
            self._win_count += 1
        elif realized_pnl < 0:
            self._loss_count += 1
        return position, realized_pnl

    def reduce_position(
        self,
        token_address: str,
        quantity: float,
        current_price_sol: float,
    ) -> tuple[Position, float]:
        """Reduce an open position by *quantity* tokens at *current_price_sol*.

        Returns the updated :class:`Position` and the realized P&L for the
        reduced portion. If *quantity* >= current position quantity, the
        position is fully closed instead.
        """
        position = self._positions.get(token_address)
        if position is None:
            raise ValueError(f"Position not found for token: {token_address}")
        if quantity <= 0:
            raise ValueError("Quantity to reduce must be positive")

        if quantity >= position.quantity:
            return self.close_position(token_address, current_price_sol)

        realized_pnl = (current_price_sol - position.entry_price_sol) * quantity
        proceeds = current_price_sol * quantity
        self._available_sol += proceeds
        self._daily_pnl_sol += realized_pnl
        if realized_pnl > 0:
            self._win_count += 1
        elif realized_pnl < 0:
            self._loss_count += 1

        position.quantity -= quantity
        position.current_price_sol = current_price_sol
        position.last_updated = datetime.now(timezone.utc).isoformat()
        position._update_unrealized()
        return position, realized_pnl

    def update_price(self, token_address: str, current_price_sol: float) -> None:
        position = self._positions.get(token_address)
        if position is None:
            return
        position.current_price_sol = current_price_sol
        position.last_updated = datetime.now(timezone.utc).isoformat()
        position._update_unrealized()

    def get_snapshot(self) -> PortfolioSnapshot:
        positions = list(self._positions.values())
        total_value = self._available_sol + sum(
            p.current_price_sol * p.quantity for p in positions
        )
        if total_value > self._peak_value_sol:
            self._peak_value_sol = total_value
        if self._peak_value_sol > 0:
            drawdown = (self._peak_value_sol - total_value) / self._peak_value_sol * 100.0
        else:
            drawdown = 0.0
        if drawdown > self._max_drawdown_percent:
            self._max_drawdown_percent = drawdown
        if self._initial_balance_sol > 0:
            total_return = (
                (total_value - self._initial_balance_sol) / self._initial_balance_sol * 100.0
            )
        else:
            total_return = 0.0
        if self._last_daily_value_sol > 0:
            daily_pnl_percent = self._daily_pnl_sol / self._last_daily_value_sol * 100.0
        else:
            daily_pnl_percent = 0.0
        sharpe = self._compute_sharpe_ratio()
        timestamp = datetime.now(timezone.utc).isoformat()
        return PortfolioSnapshot(
            timestamp=timestamp,
            total_value_sol=total_value,
            available_sol=self._available_sol,
            positions=positions,
            daily_pnl_sol=self._daily_pnl_sol,
            daily_pnl_percent=daily_pnl_percent,
            total_return_percent=total_return,
            sharpe_ratio=sharpe,
            max_drawdown_percent=self._max_drawdown_percent,
            win_count=self._win_count,
            loss_count=self._loss_count,
        )

    def _compute_sharpe_ratio(self) -> float:
        if len(self._daily_returns) < 2:
            return 0.0
        n = len(self._daily_returns)
        mean = sum(self._daily_returns) / n
        variance = sum((r - mean) ** 2 for r in self._daily_returns) / n
        std_dev = variance ** 0.5
        if std_dev == 0.0:
            return 0.0
        return mean / std_dev

    def get_position(self, token_address: str) -> Position | None:
        return self._positions.get(token_address)

    def list_positions(self) -> list[Position]:
        return list(self._positions.values())

    def daily_reset(self) -> None:
        current_value = self._available_sol + sum(
            p.current_price_sol * p.quantity for p in self._positions.values()
        )
        if self._last_daily_value_sol > 0:
            daily_return = (
                (current_value - self._last_daily_value_sol) / self._last_daily_value_sol * 100.0
            )
            self._daily_returns.append(daily_return)
        self._last_daily_value_sol = current_value
        self._daily_pnl_sol = 0.0
