from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from .trade_signal import TradeSignal

__all__ = [
    "OrderStatus",
    "Order",
    "OrderStats",
    "ExecutionLog",
    "OrderManager",
]

OrderStatus = Literal["PENDING", "SUBMITTED", "CONFIRMED", "FAILED", "CANCELLED"]


@dataclass
class Order:
    """Represents a single order in the order-management lifecycle."""

    order_id: str
    signal_id: str
    token_address: str
    amount_sol: float
    status: OrderStatus
    tx_hash: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    submitted_at: datetime | None = None
    confirmed_at: datetime | None = None
    failed_at: datetime | None = None
    error_message: str | None = None
    retry_count: int = 0
    dry_run: bool = False

    def __post_init__(self) -> None:
        if self.amount_sol < 0:
            self.amount_sol = 0.0
        if self.retry_count < 0:
            self.retry_count = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "signal_id": self.signal_id,
            "token_address": self.token_address,
            "amount_sol": self.amount_sol,
            "status": self.status,
            "tx_hash": self.tx_hash,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
            "failed_at": self.failed_at.isoformat() if self.failed_at else None,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "dry_run": self.dry_run,
        }


@dataclass
class OrderStats:
    """Aggregated statistics across all orders managed by :class:`OrderManager`."""

    total_orders: int = 0
    pending: int = 0
    submitted: int = 0
    confirmed: int = 0
    failed: int = 0
    cancelled: int = 0
    success_rate: float = 0.0
    avg_execution_time_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_orders": self.total_orders,
            "pending": self.pending,
            "submitted": self.submitted,
            "confirmed": self.confirmed,
            "failed": self.failed,
            "cancelled": self.cancelled,
            "success_rate": self.success_rate,
            "avg_execution_time_ms": self.avg_execution_time_ms,
        }


@dataclass
class ExecutionLog:
    """Audit trail entry for a state change or execution event on an order."""

    log_id: str
    order_id: str
    action: str
    timestamp: datetime
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "log_id": self.log_id,
            "order_id": self.order_id,
            "action": self.action,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "details": self.details,
        }


class OrderManager:
    """Order management and execution tracking system.

    Maintains a registry of :class:`Order` objects and provides lifecycle
    methods (create, submit, confirm, fail, cancel, retry) together with
    aggregate :class:`OrderStats`.
    """

    def __init__(self, max_retries: int = 3) -> None:
        self.max_retries = max_retries
        self._orders: dict[str, Order] = {}

    # ------------------------------------------------------------------
    # Lifecycle operations
    # ------------------------------------------------------------------

    def create_sell_order(self, token_address: str, amount_sol: float, signal_id: str) -> Order:
        """Create a new ``PENDING`` sell order from raw parameters."""
        order = Order(
            order_id=str(uuid4()),
            signal_id=signal_id,
            token_address=token_address,
            amount_sol=amount_sol,
            status="PENDING",
            dry_run=False,
        )
        self._orders[order.order_id] = order
        return order

    def create_order(self, signal: TradeSignal) -> Order:
        """Create a new ``PENDING`` order from a :class:`TradeSignal`."""
        order = Order(
            order_id=str(uuid4()),
            signal_id=signal.signal_id,
            token_address=signal.target_token,
            amount_sol=signal.recommended_amount_sol,
            status="PENDING",
            dry_run=False,
        )
        self._orders[order.order_id] = order
        return order

    def submit_order(self, order_id: str, tx_hash: str | None = None) -> Order:
        """Mark an order as ``SUBMITTED`` and record the optional tx hash."""
        order = self._get_order_or_raise(order_id)
        order.status = "SUBMITTED"
        order.submitted_at = datetime.utcnow()
        order.tx_hash = tx_hash
        return order

    def confirm_order(
        self,
        order_id: str,
        actual_amount: float,
        actual_slippage: float,
        gas_cost: float,
    ) -> Order:
        """Mark an order as ``CONFIRMED``."""
        order = self._get_order_or_raise(order_id)
        order.status = "CONFIRMED"
        order.confirmed_at = datetime.utcnow()
        return order

    def fail_order(self, order_id: str, error_message: str) -> Order:
        """Mark an order as ``FAILED`` and increment its retry counter."""
        order = self._get_order_or_raise(order_id)
        order.retry_count += 1
        order.status = "FAILED"
        order.failed_at = datetime.utcnow()
        order.error_message = error_message
        return order

    def cancel_order(self, order_id: str) -> Order:
        """Mark an order as ``CANCELLED``."""
        order = self._get_order_or_raise(order_id)
        order.status = "CANCELLED"
        return order

    def retry_order(self, order_id: str) -> Order | None:
        """Return a new ``PENDING`` order if the failed order still has retries left.

        Returns ``None`` when the order is not in ``FAILED`` status or when its
        ``retry_count`` has reached ``max_retries``.
        """
        order = self._get_order_or_raise(order_id)
        if order.status != "FAILED":
            return None
        if order.retry_count >= self.max_retries:
            return None
        new_order = Order(
            order_id=str(uuid4()),
            signal_id=order.signal_id,
            token_address=order.token_address,
            amount_sol=order.amount_sol,
            status="PENDING",
            retry_count=order.retry_count,
            dry_run=order.dry_run,
        )
        self._orders[new_order.order_id] = new_order
        return new_order

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_order(self, order_id: str) -> Order | None:
        """Return the order or ``None`` if not found."""
        return self._orders.get(order_id)

    def list_orders(self, status: str | None = None) -> list[Order]:
        """Return all orders, optionally filtered by status."""
        if status is None:
            return list(self._orders.values())
        return [o for o in self._orders.values() if o.status == status]

    def get_stats(self) -> OrderStats:
        """Compute aggregate order statistics."""
        total = len(self._orders)
        pending = sum(1 for o in self._orders.values() if o.status == "PENDING")
        submitted = sum(1 for o in self._orders.values() if o.status == "SUBMITTED")
        confirmed = sum(1 for o in self._orders.values() if o.status == "CONFIRMED")
        failed = sum(1 for o in self._orders.values() if o.status == "FAILED")
        cancelled = sum(1 for o in self._orders.values() if o.status == "CANCELLED")

        terminal = confirmed + failed
        success_rate = confirmed / terminal if terminal > 0 else 0.0

        exec_times: list[float] = []
        for o in self._orders.values():
            if o.status == "CONFIRMED" and o.submitted_at is not None and o.confirmed_at is not None:
                delta = o.confirmed_at - o.submitted_at
                exec_times.append(delta.total_seconds() * 1000.0)

        avg_exec_time = sum(exec_times) / len(exec_times) if exec_times else 0.0

        return OrderStats(
            total_orders=total,
            pending=pending,
            submitted=submitted,
            confirmed=confirmed,
            failed=failed,
            cancelled=cancelled,
            success_rate=success_rate,
            avg_execution_time_ms=avg_exec_time,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_order_or_raise(self, order_id: str) -> Order:
        order = self._orders.get(order_id)
        if order is None:
            raise ValueError(f"Order not found: {order_id}")
        return order
