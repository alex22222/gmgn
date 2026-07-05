from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

from .backtest_strategies import BuySignal


__all__ = [
    "TPOrder",
    "SLOrder",
    "TradeSignal",
    "TradeExecution",
]


@dataclass(frozen=True)
class TPOrder:
    """Take-profit order configuration for a trade signal."""

    level: int                        # 1, 2, 3...
    trigger_percent: float              # +100%, +300%, etc
    sell_percent: float                 # 50%, 30%, etc

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "trigger_percent": self.trigger_percent,
            "sell_percent": self.sell_percent,
        }


@dataclass(frozen=True)
class SLOrder:
    """Stop-loss order configuration for a trade signal."""

    trigger_percent: float              # -30%, -65%, etc
    sell_percent: float = 100.0         # usually 100%

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger_percent": self.trigger_percent,
            "sell_percent": self.sell_percent,
        }


@dataclass(frozen=True)
class TradeSignal:
    """A structured trade signal derived from wallet activity or manual entry.

    Represents a decision to act on a token (buy, add, reduce, or exit) with
    full risk-management parameters attached (TP/SL, slippage, MEV protection).
    """

    signal_id: str
    wallet_address: str
    target_token: str
    signal_type: Literal["NEW_POSITION", "ADD_POSITION", "REDUCE", "EXIT"]
    urgency_score: int                  # 0-100
    confidence_score: int                 # 0-100
    quality_score: int                    # 0-100 (calculated)
    recommended_amount_sol: float
    max_slippage_percent: float = 30.0
    priority_fee_sol: float = 0.01
    mev_protection: Literal["OFF", "REDUCED", "SECURE"] = "SECURE"
    tp_orders: tuple[TPOrder, ...] = field(default_factory=tuple)
    sl_order: SLOrder | None = None
    expires_at: datetime | None = None    # default 10 min from creation
    chain: str = "sol"
    received_at: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self) -> None:
        # Clamp scores to valid ranges
        if not (0 <= self.urgency_score <= 100):
            object.__setattr__(self, "urgency_score", max(0, min(100, self.urgency_score)))
        if not (0 <= self.confidence_score <= 100):
            object.__setattr__(self, "confidence_score", max(0, min(100, self.confidence_score)))
        if not (0 <= self.quality_score <= 100):
            object.__setattr__(self, "quality_score", max(0, min(100, self.quality_score)))
        if not (0 <= self.max_slippage_percent <= 100):
            object.__setattr__(self, "max_slippage_percent", max(0, min(100, self.max_slippage_percent)))
        if not (0 <= self.priority_fee_sol <= 1.0):
            object.__setattr__(self, "priority_fee_sol", max(0.0, min(1.0, self.priority_fee_sol)))
        if self.recommended_amount_sol <= 0:
            object.__setattr__(self, "recommended_amount_sol", 0.0)

    @classmethod
    def from_buy_signal(cls, buy_signal: BuySignal, wallet_score: float = 0.0) -> "TradeSignal":
        """Convert a BuySignal (from SignalEngine) to a TradeSignal."""
        # Derive urgency from wallet score (0-100 → 0-100)
        urgency = int(min(100.0, max(0.0, wallet_score)))
        # Derive confidence from BuySignal.confidence (0-1 → 0-100)
        confidence = int(buy_signal.confidence * 100.0)
        quality = int((urgency + confidence) / 2)
        # Default TP/SL based on conservative spec
        tp_orders = (
            TPOrder(level=1, trigger_percent=100.0, sell_percent=50.0),
            TPOrder(level=2, trigger_percent=300.0, sell_percent=50.0),
        )
        sl_order = SLOrder(trigger_percent=-65.0, sell_percent=100.0)
        # Amount: copy the BuySignal amount, capped at 1 SOL
        amount = min(buy_signal.amount_sol, 1.0)
        return cls(
            signal_id=str(uuid4()),
            wallet_address=buy_signal.wallet_address,
            target_token=buy_signal.token_address,
            signal_type="NEW_POSITION",
            urgency_score=urgency,
            confidence_score=confidence,
            quality_score=quality,
            recommended_amount_sol=amount,
            max_slippage_percent=30.0,
            priority_fee_sol=0.01,
            mev_protection="SECURE",
            tp_orders=tp_orders,
            sl_order=sl_order,
            expires_at=datetime.utcnow() + timedelta(minutes=10),
            chain="sol",
            received_at=datetime.utcnow(),
        )

    def is_expired(self) -> bool:
        """Return True if the signal has passed its expiration time."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "wallet_address": self.wallet_address,
            "target_token": self.target_token,
            "signal_type": self.signal_type,
            "urgency_score": self.urgency_score,
            "confidence_score": self.confidence_score,
            "quality_score": self.quality_score,
            "recommended_amount_sol": self.recommended_amount_sol,
            "max_slippage_percent": self.max_slippage_percent,
            "priority_fee_sol": self.priority_fee_sol,
            "mev_protection": self.mev_protection,
            "tp_orders": [tp.to_dict() for tp in self.tp_orders],
            "sl_order": self.sl_order.to_dict() if self.sl_order else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "chain": self.chain,
            "received_at": self.received_at.isoformat(),
        }

    def with_quality_score(self, quality_score: int) -> "TradeSignal":
        """Return a new TradeSignal with an updated quality_score."""
        return replace(self, quality_score=quality_score)


@dataclass(frozen=True)
class TradeExecution:
    """Record of a single trade execution attempt and its outcome."""

    execution_id: str
    signal_id: str
    status: Literal["PENDING", "SUBMITTED", "CONFIRMED", "FAILED", "CANCELLED"]
    tx_hash: str | None = None
    actual_amount_sol: float = 0.0
    actual_slippage_percent: float = 0.0
    gas_cost_sol: float = 0.0
    mev_loss_sol: float | None = None
    received_at: datetime = field(default_factory=datetime.utcnow)
    decided_at: datetime | None = None
    submitted_at: datetime | None = None
    confirmed_at: datetime | None = None
    error_message: str | None = None
    dry_run: bool = False                # True if simulated

    def __post_init__(self) -> None:
        if self.actual_amount_sol < 0:
            object.__setattr__(self, "actual_amount_sol", 0.0)
        if self.actual_slippage_percent < 0:
            object.__setattr__(self, "actual_slippage_percent", 0.0)
        if self.gas_cost_sol < 0:
            object.__setattr__(self, "gas_cost_sol", 0.0)

    def duration_ms(self) -> float | None:
        """Return total execution duration from received to confirmed (in ms)."""
        if self.received_at is None or self.confirmed_at is None:
            return None
        delta = self.confirmed_at - self.received_at
        return delta.total_seconds() * 1000.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "signal_id": self.signal_id,
            "status": self.status,
            "tx_hash": self.tx_hash,
            "actual_amount_sol": self.actual_amount_sol,
            "actual_slippage_percent": self.actual_slippage_percent,
            "gas_cost_sol": self.gas_cost_sol,
            "mev_loss_sol": self.mev_loss_sol,
            "received_at": self.received_at.isoformat(),
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
            "error_message": self.error_message,
            "dry_run": self.dry_run,
        }
