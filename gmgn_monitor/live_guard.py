"""Last-line checks for a live copy order.

Tiny auto-confirm is allowed only while the automation gate is open and the
order stays inside ``config/copy_risk.json``. These checks run again at
submit time, including when the executor was constructed with auto-confirm.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .automation_gate import evaluate_gate
from .copy_risk import CopyRiskProfile
from .serialization import load_json


DEFAULT_GATE_PATH = Path(__file__).resolve().parent.parent / "config" / "automation_gate.json"


def load_automation_gate(path: Path | None = None) -> dict[str, Any]:
    """Load the gate file. A missing file fails closed."""
    target = path or DEFAULT_GATE_PATH
    if not target.exists():
        return {}
    raw = load_json(target, label="automation gate config")
    if not isinstance(raw, dict):
        return {}
    return raw


def live_buy_block_reason(
    *,
    amount_sol: float,
    daily_pnl_sol: float,
    slippage_percent: float,
    profile: CopyRiskProfile,
    gate_config: dict[str, Any],
) -> str | None:
    """Return why a live buy must not be submitted."""
    gate_reason = _gate_block_reason(gate_config)
    if gate_reason:
        return gate_reason
    return profile.order_block_reason(amount_sol, daily_pnl_sol, slippage_percent)


def live_sell_block_reason(
    *,
    slippage_percent: float,
    profile: CopyRiskProfile,
    gate_config: dict[str, Any],
) -> str | None:
    """Return why a live sell must not be submitted."""
    gate_reason = _gate_block_reason(gate_config)
    if gate_reason:
        return gate_reason
    if slippage_percent - profile.max_slippage_percent > 1e-9:
        return "exceeds max_slippage_percent"
    return None


def tiny_auto_confirm_allowed(*, requested: bool, gate_config: dict[str, Any]) -> bool:
    """Skip the stdin prompt only when the operator asked and the gate is open."""
    if not requested:
        return False
    return _gate_block_reason(gate_config) is None


def _gate_block_reason(gate_config: dict[str, Any]) -> str | None:
    status = str(evaluate_gate(gate_config or {}).get("status") or "blocked")
    if status != "auto_trading_enabled":
        return f"automation gate is {status}"
    return None
