"""Hard guards for tiny_real copy trading.

Implements the tracking-bot failure-mode rules from the Odaily / Grok Bot
analysis: chase-premium skip, signal freshness, per-leader exposure caps,
consecutive-loss demotion, and security hard rejects.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .file_io import atomic_write_text
from .serialization import load_json


__all__ = [
    "CopyTradeContext",
    "CopyTradeGuardConfig",
    "GuardDecision",
    "CopyTradeGuards",
    "load_copy_trade_guard_config",
    "demote_leader_in_whitelist",
]


@dataclass(frozen=True)
class CopyTradeGuardConfig:
    max_chase_percent: float = 15.0
    max_signal_age_seconds: float = 20.0
    consecutive_loss_limit: int = 3
    max_wallet_daily_exposure_sol: float = 0.01
    max_single_trade_sol: float = 0.01
    require_known_security: bool = False
    demote_mode: str = "observe"

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_chase_percent": self.max_chase_percent,
            "max_signal_age_seconds": self.max_signal_age_seconds,
            "consecutive_loss_limit": self.consecutive_loss_limit,
            "max_wallet_daily_exposure_sol": self.max_wallet_daily_exposure_sol,
            "max_single_trade_sol": self.max_single_trade_sol,
            "require_known_security": self.require_known_security,
            "demote_mode": self.demote_mode,
        }


@dataclass(frozen=True)
class CopyTradeContext:
    """Per-signal market / security facts used by buy guards."""

    leader_entry_price: float | None = None
    expected_entry_price: float | None = None
    leader_traded_at: datetime | None = None
    amount_sol: float | None = None
    honeypot_risk: bool | None = None
    lp_burned_or_locked: bool | None = None
    top10_holder_percent: float | None = None
    mint_authority_active: bool | None = None
    freeze_authority_active: bool | None = None


@dataclass(frozen=True)
class GuardDecision:
    allow: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"allow": self.allow, "reason": self.reason}


def load_copy_trade_guard_config(path: Path | None = None) -> CopyTradeGuardConfig:
    config_path = path or Path("config/copy_trade_guards.json")
    if not config_path.exists():
        return CopyTradeGuardConfig()
    raw = load_json(config_path)
    if not isinstance(raw, dict):
        return CopyTradeGuardConfig()
    return CopyTradeGuardConfig(
        max_chase_percent=float(raw.get("max_chase_percent", 15.0)),
        max_signal_age_seconds=float(raw.get("max_signal_age_seconds", 20.0)),
        consecutive_loss_limit=int(raw.get("consecutive_loss_limit", 3)),
        max_wallet_daily_exposure_sol=float(raw.get("max_wallet_daily_exposure_sol", 0.01)),
        max_single_trade_sol=float(raw.get("max_single_trade_sol", 0.01)),
        require_known_security=bool(raw.get("require_known_security", False)),
        demote_mode=str(raw.get("demote_mode") or "observe"),
    )


def demote_leader_in_whitelist(
    whitelist_path: Path,
    wallet_address: str,
    *,
    reason: str,
    demote_mode: str = "observe",
) -> bool:
    """Disable a leader and switch it to observe. Returns True if changed."""
    raw = load_json(whitelist_path)
    if not isinstance(raw, dict):
        return False
    wallets = raw.get("wallets")
    if not isinstance(wallets, list):
        return False
    changed = False
    now = datetime.now(timezone.utc).isoformat()
    for wallet in wallets:
        if not isinstance(wallet, dict):
            continue
        if str(wallet.get("wallet_address") or "") != wallet_address:
            continue
        wallet["enabled"] = False
        wallet["mode"] = demote_mode
        wallet["copy_weight"] = 0.0
        notes = str(wallet.get("notes") or "")
        tag = f"[auto-demote {now}] {reason}"
        wallet["notes"] = f"{notes} | {tag}" if notes else tag
        changed = True
        break
    if not changed:
        return False
    raw["updated_at"] = now
    atomic_write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", whitelist_path)
    return True


@dataclass
class CopyTradeGuards:
    """Stateful buy-side guards shared across auto-copy cycles."""

    config: CopyTradeGuardConfig = field(default_factory=CopyTradeGuardConfig)
    consecutive_losses: dict[str, int] = field(default_factory=dict)
    daily_exposure_sol: dict[str, float] = field(default_factory=dict)
    exposure_day: date | None = None
    pending_demotions: list[dict[str, str]] = field(default_factory=list)

    def _roll_exposure_day(self, now: datetime | None = None) -> None:
        today = (now or datetime.now(timezone.utc)).date()
        if self.exposure_day != today:
            self.exposure_day = today
            self.daily_exposure_sol.clear()

    def evaluate_buy(
        self,
        wallet_address: str,
        context: CopyTradeContext,
        *,
        now: datetime | None = None,
    ) -> GuardDecision:
        """Return whether a NEW_POSITION copy buy may proceed."""
        now = now or datetime.now(timezone.utc)
        self._roll_exposure_day(now)

        amount = context.amount_sol
        if amount is not None and amount > self.config.max_single_trade_sol + 1e-12:
            return GuardDecision(False, "position_size_cap")

        if self.consecutive_losses.get(wallet_address, 0) >= self.config.consecutive_loss_limit:
            return GuardDecision(False, "leader_demoted_consecutive_losses")

        used = self.daily_exposure_sol.get(wallet_address, 0.0)
        if amount is not None and used + amount > self.config.max_wallet_daily_exposure_sol + 1e-12:
            return GuardDecision(False, "wallet_daily_exposure_cap")

        age_decision = self._check_freshness(context, now)
        if not age_decision.allow:
            return age_decision

        chase_decision = self._check_chase(context)
        if not chase_decision.allow:
            return chase_decision

        security_decision = self._check_security(context)
        if not security_decision.allow:
            return security_decision

        return GuardDecision(True, "ok")

    def reserve_exposure(self, wallet_address: str, amount_sol: float, *, now: datetime | None = None) -> None:
        """Record planned/executed buy notional against the daily wallet cap."""
        self._roll_exposure_day(now)
        if amount_sol <= 0:
            return
        self.daily_exposure_sol[wallet_address] = self.daily_exposure_sol.get(wallet_address, 0.0) + amount_sol

    def record_copy_outcome(self, wallet_address: str, pnl_sol: float) -> bool:
        """Update consecutive-loss streak. Returns True if the leader should demote."""
        if pnl_sol >= 0:
            self.consecutive_losses[wallet_address] = 0
            return False
        streak = self.consecutive_losses.get(wallet_address, 0) + 1
        self.consecutive_losses[wallet_address] = streak
        if streak >= self.config.consecutive_loss_limit:
            self.pending_demotions.append(
                {
                    "wallet_address": wallet_address,
                    "reason": f"consecutive copy losses >= {self.config.consecutive_loss_limit}",
                }
            )
            return True
        return False

    def drain_demotions(self) -> list[dict[str, str]]:
        pending = list(self.pending_demotions)
        self.pending_demotions.clear()
        return pending

    def _check_freshness(self, context: CopyTradeContext, now: datetime) -> GuardDecision:
        traded_at = context.leader_traded_at
        if traded_at is None:
            return GuardDecision(True, "ok")
        if traded_at.tzinfo is None:
            traded_at = traded_at.replace(tzinfo=timezone.utc)
        age = (now - traded_at).total_seconds()
        if age > self.config.max_signal_age_seconds:
            return GuardDecision(False, "signal_stale")
        if age < -5:
            return GuardDecision(False, "signal_timestamp_invalid")
        return GuardDecision(True, "ok")

    def _check_chase(self, context: CopyTradeContext) -> GuardDecision:
        leader = context.leader_entry_price
        expected = context.expected_entry_price
        if leader is None or expected is None:
            return GuardDecision(True, "ok")
        if leader <= 0 or expected <= 0:
            return GuardDecision(False, "invalid_price")
        chase_percent = (expected / leader - 1.0) * 100.0
        if chase_percent > self.config.max_chase_percent:
            return GuardDecision(False, "chase_premium")
        return GuardDecision(True, "ok")

    def _check_security(self, context: CopyTradeContext) -> GuardDecision:
        known_values = [
            context.honeypot_risk,
            context.lp_burned_or_locked,
            context.top10_holder_percent,
            context.mint_authority_active,
            context.freeze_authority_active,
        ]
        if self.config.require_known_security and all(value is None for value in known_values):
            return GuardDecision(False, "security_unknown")

        if context.honeypot_risk is True:
            return GuardDecision(False, "honeypot")
        if context.lp_burned_or_locked is False:
            return GuardDecision(False, "lp_unlocked")
        if context.mint_authority_active is True:
            return GuardDecision(False, "mint_authority_active")
        if context.freeze_authority_active is True:
            return GuardDecision(False, "freeze_authority_active")
        if context.top10_holder_percent is not None and context.top10_holder_percent >= 50.0:
            return GuardDecision(False, "top10_concentration")
        return GuardDecision(True, "ok")
