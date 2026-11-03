"""Paper copy trading against live leader activity.

Signals come from ``gmgn-cli portfolio activity``. Fills stay local: this
module never calls the swap endpoint.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .copy_risk import CopyRiskProfile, load_copy_risk
from .portfolio_tracker import PortfolioTracker
from .real_trade_executor import ExecutionResult
from .risk_manager import RiskCheckResult, RiskLimits, RiskManager
from .sell_executor import SellExecution, SellExecutionResult, SellSignal
from .trade_signal import SLOrder, TPOrder, TradeExecution, TradeSignal


PAPER_MODES = {"paper", "dryrun", "dry_run"}
DEFAULT_LOOKBACK_DAYS = 30
DEFAULT_ACTIVITY_LIMIT = 20
_RESET_AT_RE = re.compile(
    r"resets at (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"
)


class GmgnCliError(RuntimeError):
    """``gmgn-cli`` failed for a reason other than a rate limit."""


class GmgnRateLimitError(GmgnCliError):
    """GMGN asked us to wait before the next read."""

    def __init__(self, message: str, reset_at: datetime | None) -> None:
        super().__init__(message)
        self.reset_at = reset_at


@dataclass(frozen=True)
class ObservedLeaderSignal:
    """A real leader fill plus the paper signal derived from it."""

    signal: TradeSignal
    label: str
    symbol: str
    event_type: str
    event_time: datetime
    age_hours: float
    tx_hash: str
    leader_quote_amount: float
    leader_cost_usd: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal.signal_id,
            "wallet_address": self.signal.wallet_address,
            "label": self.label,
            "symbol": self.symbol,
            "event_type": self.event_type,
            "signal_type": self.signal.signal_type,
            "token": self.signal.target_token,
            "event_time": self.event_time.isoformat(),
            "age_hours": round(self.age_hours, 2),
            "tx_hash": self.tx_hash,
            "leader_quote_amount": self.leader_quote_amount,
            "leader_cost_usd": self.leader_cost_usd,
            "paper_amount_sol": self.signal.recommended_amount_sol,
        }


def resolve_trade_mode(
    config: dict[str, Any],
    *,
    paper: bool = False,
    real: bool = False,
) -> str:
    """Return ``paper`` or ``real``.

    A paper config cannot be overridden into a live submission. Real execution
    requires both ``trade_mode=real`` and an explicit real request.
    """
    if paper and real:
        raise ValueError("choose either paper or real")
    configured = str(config.get("trade_mode") or "paper").strip().lower()
    if paper:
        return "paper"
    if real:
        if configured != "real":
            raise ValueError(
                f"refusing real execution while trade_mode={configured or 'paper'}"
            )
        return "real"
    if configured in PAPER_MODES or configured in {"", "real"}:
        return "paper"
    raise ValueError(f"unsupported trade_mode: {configured}")


def copy_trading_enabled(config: dict[str, Any]) -> bool:
    settings = config.get("global_settings")
    if not isinstance(settings, dict):
        return False
    return bool(settings.get("copy_trading_enabled"))


def paper_lookback(config: dict[str, Any] | None = None, profile: CopyRiskProfile | None = None) -> timedelta:
    """Report window for leader activity. Execution uses a shorter age gate."""
    del config
    active = profile or load_copy_risk()
    days = active.report_lookback_days if active.report_lookback_days > 0 else DEFAULT_LOOKBACK_DAYS
    return timedelta(days=days)


def find_gmgn_cli() -> str:
    found = shutil.which("gmgn-cli")
    if found:
        return found
    candidate = Path.home() / ".local" / "bin" / "gmgn-cli"
    if candidate.is_file():
        return str(candidate)
    raise GmgnCliError("gmgn-cli is not installed")


def parse_reset_at(message: str) -> datetime | None:
    match = _RESET_AT_RE.search(message)
    if match is None:
        return None
    parsed = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
    return parsed.replace(tzinfo=timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _naive_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(timezone.utc).replace(tzinfo=None)


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _event_time(entry: dict[str, Any]) -> datetime | None:
    raw = entry.get("timestamp")
    if isinstance(raw, (int, float)) and raw > 0:
        return datetime.fromtimestamp(float(raw), tz=timezone.utc)
    if isinstance(raw, str) and raw:
        text = raw.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def _token_address(entry: dict[str, Any]) -> str:
    token = entry.get("token")
    if isinstance(token, dict):
        address = token.get("address") or token.get("token_address") or ""
        if address:
            return str(address)
    for key in ("base_address", "token_address", "address"):
        value = entry.get(key)
        if value:
            return str(value)
    return ""


def _token_symbol(entry: dict[str, Any]) -> str:
    token = entry.get("token")
    if isinstance(token, dict) and token.get("symbol"):
        return str(token["symbol"])
    base = entry.get("base_token")
    if isinstance(base, dict) and base.get("symbol"):
        return str(base["symbol"])
    return ""


def _event_type(entry: dict[str, Any]) -> str:
    raw = entry.get("event_type") or entry.get("type") or entry.get("side") or ""
    return str(raw).strip().lower()


def paper_amount_sol(entry: dict[str, Any], cap_sol: float) -> float:
    """Size a paper copy from the leader's SOL quote, never above the cap."""
    cap = max(0.0, cap_sol)
    quote = _as_float(entry.get("quote_amount"))
    # Leader quotes above 20 SOL are not native SOL on this feed (USD leaks
    # into quote_amount). Keep the paper clip instead of copying that number.
    if 0 < quote <= 20:
        return min(quote, cap) if cap else quote
    return cap


def parse_activity_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    activities = payload.get("activities")
    if isinstance(activities, list):
        return [item for item in activities if isinstance(item, dict)]
    data = payload.get("data")
    if isinstance(data, dict):
        nested = data.get("activities")
        if isinstance(nested, list):
            return [item for item in nested if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _risk_orders(wallet: dict[str, Any]) -> tuple[tuple[TPOrder, ...], SLOrder]:
    limits = wallet.get("risk_limits") if isinstance(wallet.get("risk_limits"), dict) else {}
    steps = limits.get("take_profit_steps") if isinstance(limits, dict) else []
    if not isinstance(steps, list):
        steps = []
    orders = tuple(
        TPOrder(
            level=index + 1,
            trigger_percent=_as_float(step.get("price_change_percent")),
            sell_percent=_as_float(step.get("sell_percent")) or 50.0,
        )
        for index, step in enumerate(steps)
        if isinstance(step, dict)
    )
    if not orders:
        orders = (
            TPOrder(level=1, trigger_percent=100.0, sell_percent=50.0),
            TPOrder(level=2, trigger_percent=300.0, sell_percent=50.0),
        )
    stop = _as_float(limits.get("stop_loss_percent")) if isinstance(limits, dict) else 0.0
    if stop == 0.0:
        stop = -40.0
    return orders, SLOrder(trigger_percent=stop, sell_percent=100.0)


def select_leader_signals(
    activities: list[dict[str, Any]],
    wallet: dict[str, Any],
    *,
    now: datetime | None = None,
    lookback: timedelta | None = None,
) -> list[ObservedLeaderSignal]:
    """Keep the newest buy and newest sell inside the lookback window."""
    moment = now or _utc_now()
    window = lookback if lookback is not None else timedelta(days=DEFAULT_LOOKBACK_DAYS)
    address = str(wallet.get("wallet_address") or "")
    score = int(min(100.0, max(0.0, _as_float(wallet.get("total_score") or 50.0))))
    limits = wallet.get("risk_limits") if isinstance(wallet.get("risk_limits"), dict) else {}
    cap = _as_float(limits.get("max_single_trade_sol")) or 0.01
    slippage = _as_float(limits.get("slippage_percent")) or 2.0
    tp_orders, sl_order = _risk_orders(wallet)
    newest: dict[str, tuple[datetime, dict[str, Any]]] = {}

    for entry in activities:
        kind = _event_type(entry)
        if kind not in {"buy", "sell"}:
            continue
        if not _token_address(entry):
            continue
        event_time = _event_time(entry)
        if event_time is None or event_time < moment - window or event_time > moment + timedelta(minutes=5):
            continue
        current = newest.get(kind)
        if current is None or event_time > current[0]:
            newest[kind] = (event_time, entry)

    observed: list[ObservedLeaderSignal] = []
    for kind, (event_time, entry) in newest.items():
        token = _token_address(entry)
        tx_hash = str(entry.get("tx_hash") or entry.get("transaction_hash") or "")
        amount = paper_amount_sol(entry, cap)
        if amount <= 0 or not token:
            continue
        signal_type = "EXIT" if kind == "sell" else "NEW_POSITION"
        signal_id = f"paper-{tx_hash[:12] or int(event_time.timestamp())}-{token[:6]}"
        signal = TradeSignal(
            signal_id=signal_id,
            wallet_address=address,
            target_token=token,
            signal_type=signal_type,
            urgency_score=score,
            confidence_score=70,
            quality_score=score,
            recommended_amount_sol=amount,
            max_slippage_percent=slippage,
            priority_fee_sol=0.0,
            mev_protection="SECURE",
            tp_orders=tp_orders,
            sl_order=sl_order,
            chain="sol",
            received_at=_naive_utc(event_time),
        )
        age_hours = max(0.0, (moment - event_time).total_seconds() / 3600.0)
        observed.append(
            ObservedLeaderSignal(
                signal=signal,
                label=str(wallet.get("label") or ""),
                symbol=_token_symbol(entry),
                event_type=kind,
                event_time=event_time,
                age_hours=age_hours,
                tx_hash=tx_hash,
                leader_quote_amount=_as_float(entry.get("quote_amount")),
                leader_cost_usd=_as_float(entry.get("cost_usd")),
            )
        )
    observed.sort(key=lambda item: item.event_time, reverse=True)
    return observed


def split_executable_signals(
    observed: list[ObservedLeaderSignal],
    profile: CopyRiskProfile,
    *,
    now: datetime | None = None,
) -> tuple[list[ObservedLeaderSignal], list[dict[str, Any]]]:
    """Keep only trades inside the copy age gate, and cap new buys per day.

    Older trades stay visible as observations. They are not sent to CSS.
    """
    moment = now or _utc_now()
    max_age = timedelta(minutes=profile.max_signal_age_minutes)
    executable: list[ObservedLeaderSignal] = []
    held_back: list[dict[str, Any]] = []
    buy_count = 0
    for item in observed:
        age = moment - item.event_time
        if age > max_age:
            held_back.append({**item.to_dict(), "hold_reason": "stale"})
            continue
        if item.signal.signal_type == "NEW_POSITION" and buy_count >= profile.max_daily_trades:
            held_back.append({**item.to_dict(), "hold_reason": "max_daily_trades"})
            continue
        if item.signal.signal_type == "NEW_POSITION":
            buy_count += 1
        refreshed = replace(item.signal, received_at=_naive_utc(moment))
        executable.append(replace(item, signal=refreshed))
    return executable, held_back


def fetch_wallet_activity(
    wallet_address: str,
    *,
    chain: str = "sol",
    limit: int = DEFAULT_ACTIVITY_LIMIT,
    cli_path: str | None = None,
    timeout_seconds: float = 45.0,
) -> list[dict[str, Any]]:
    """Read one leader's recent fills through ``gmgn-cli``."""
    command = [
        cli_path or find_gmgn_cli(),
        "portfolio",
        "activity",
        "--chain",
        chain,
        "--wallet",
        wallet_address,
        "--limit",
        str(limit),
        "--raw",
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "gmgn-cli failed").strip()
        if "429" in message or "RATE_LIMIT" in message:
            raise GmgnRateLimitError(message, parse_reset_at(message))
        raise GmgnCliError(message)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise GmgnCliError("gmgn-cli portfolio activity returned invalid JSON") from exc
    return parse_activity_payload(payload)


def collect_leader_signals(
    wallets: list[dict[str, Any]],
    config: dict[str, Any],
    *,
    now: datetime | None = None,
    sleeper: Any = time.sleep,
    activity_loader: Any = None,
    profile: CopyRiskProfile | None = None,
) -> tuple[list[ObservedLeaderSignal], list[dict[str, Any]]]:
    """Fetch each enabled leader once, waiting out a single rate-limit window."""
    del config
    loader = activity_loader or fetch_wallet_activity
    active = profile or load_copy_risk()
    lookback = paper_lookback(profile=active)
    moment = now or _utc_now()
    observed: list[ObservedLeaderSignal] = []
    notes: list[dict[str, Any]] = []
    limited = False

    for wallet in wallets:
        address = str(wallet.get("wallet_address") or "")
        if not address:
            continue
        score = _as_float(wallet.get("total_score"))
        if score < active.min_leader_score:
            notes.append({
                "wallet_address": address,
                "label": wallet.get("label") or "",
                "status": "below_score",
                "total_score": score,
                "min_leader_score": active.min_leader_score,
            })
            continue
        sized = dict(wallet)
        limits = dict(sized.get("risk_limits") or {})
        wallet_cap = _as_float(limits.get("max_single_trade_sol")) or active.max_single_trade_sol
        limits["max_single_trade_sol"] = min(wallet_cap, active.max_single_trade_sol)
        slippage = _as_float(limits.get("slippage_percent")) or active.default_slippage_percent
        limits["slippage_percent"] = min(slippage, active.max_slippage_percent)
        sized["risk_limits"] = limits
        wallet = sized
        activities: list[dict[str, Any]] | None = None
        error = ""
        for attempt in range(2):
            try:
                activities = loader(address)
                break
            except GmgnRateLimitError as exc:
                error = str(exc)
                if limited or attempt == 1 or exc.reset_at is None:
                    activities = None
                    break
                wait_seconds = (exc.reset_at - _utc_now()).total_seconds() + 2.0
                if wait_seconds > 180:
                    activities = None
                    break
                limited = True
                if wait_seconds > 0:
                    sleeper(wait_seconds)
            except (GmgnCliError, subprocess.TimeoutExpired, OSError) as exc:
                error = str(exc)
                activities = None
                break
        if activities is None:
            notes.append({
                "wallet_address": address,
                "label": wallet.get("label") or "",
                "status": "error",
                "error": error,
            })
            continue
        selected = select_leader_signals(
            activities,
            wallet,
            now=moment,
            lookback=lookback,
        )
        newest_time = None
        for entry in activities:
            event_time = _event_time(entry)
            if event_time is not None and (newest_time is None or event_time > newest_time):
                newest_time = event_time
        notes.append({
            "wallet_address": address,
            "label": wallet.get("label") or "",
            "status": "ok",
            "activity_count": len(activities),
            "selected": len(selected),
            "newest_event_time": newest_time.isoformat() if newest_time else None,
            "lookback_days": lookback.days,
        })
        observed.extend(selected)
        sleeper(1.0)
    return observed, notes


class PaperBuyExecutor:
    """Record a paper buy. Does not submit a swap."""

    def __init__(
        self,
        portfolio: PortfolioTracker | None = None,
        risk_limits: RiskLimits | None = None,
        copy_risk: CopyRiskProfile | None = None,
    ) -> None:
        self._copy_risk = copy_risk or load_copy_risk()
        self._portfolio = portfolio or PortfolioTracker(initial_balance_sol=10.0)
        self._risk_limits = risk_limits or self._copy_risk.to_risk_limits()
        self._risk_manager = RiskManager(self._risk_limits)

    def execute_trade(self, signal: TradeSignal) -> ExecutionResult:
        snapshot = self._portfolio.get_snapshot()
        blocked = self._copy_risk.order_block_reason(
            signal.recommended_amount_sol,
            snapshot.daily_pnl_sol,
            signal.max_slippage_percent,
        )
        if blocked:
            return ExecutionResult(
                success=False,
                trade_execution=None,
                order_id=None,
                tx_hash=None,
                error_message=blocked,
                gas_cost_sol=0.0,
                actual_slippage_percent=0.0,
                confirmation_time_ms=0.0,
            )
        risk_result = self._risk_manager.check_trade(
            signal=signal,
            current_portfolio_value=snapshot.total_value_sol,
            open_positions=[position.to_dict() for position in snapshot.positions],
        )
        if risk_result != RiskCheckResult.ALLOW:
            return ExecutionResult(
                success=False,
                trade_execution=None,
                order_id=None,
                tx_hash=None,
                error_message=f"Risk check failed: {risk_result.name}",
                gas_cost_sol=0.0,
                actual_slippage_percent=0.0,
                confirmation_time_ms=0.0,
            )
        order_id = str(uuid4())
        tx_hash = f"paper-{order_id[:8]}"
        trade = TradeExecution(
            execution_id=order_id,
            signal_id=signal.signal_id,
            status="CONFIRMED",
            tx_hash=tx_hash,
            actual_amount_sol=signal.recommended_amount_sol,
            actual_slippage_percent=0.0,
            gas_cost_sol=0.0,
            dry_run=True,
        )
        return ExecutionResult(
            success=True,
            trade_execution=trade,
            order_id=order_id,
            tx_hash=tx_hash,
            error_message=None,
            gas_cost_sol=0.0,
            actual_slippage_percent=0.0,
            confirmation_time_ms=0.0,
        )


class PaperSellExecutor:
    """Close or reduce a local paper position. Does not submit a swap."""

    def __init__(self, portfolio: PortfolioTracker) -> None:
        self._portfolio = portfolio

    def get_token_balance(self, token_address: str) -> float:
        position = self._portfolio.get_position(token_address)
        if position is None:
            return 0.0
        return position.quantity

    def execute_sell(self, sell_signal: SellSignal) -> SellExecutionResult:
        received_at = _utc_now()
        execution_id = str(uuid4())
        balance = self.get_token_balance(sell_signal.token_address)
        if balance <= 0.0:
            execution = SellExecution(
                execution_id=execution_id,
                signal_id=sell_signal.signal_id,
                status="FAILED",
                error_message="Zero token balance",
                received_at=received_at,
            )
            return SellExecutionResult(
                success=False,
                sell_execution=execution.to_dict(),
                order_id=None,
                tx_hash=None,
                error_message="Zero token balance",
                gas_cost_sol=0.0,
                actual_slippage_percent=0.0,
                confirmation_time_ms=0.0,
            )
        position = self._portfolio.get_position(sell_signal.token_address)
        assert position is not None
        sell_quantity = balance * sell_signal.sell_percent / 100.0
        price = position.current_price_sol
        if sell_signal.sell_percent >= 99.9 or sell_quantity >= balance:
            self._portfolio.close_position(sell_signal.token_address, exit_price_sol=price)
        else:
            self._portfolio.reduce_position(
                sell_signal.token_address,
                quantity=sell_quantity,
                current_price_sol=price,
            )
        tx_hash = f"paper-sell-{execution_id[:8]}"
        execution = SellExecution(
            execution_id=execution_id,
            signal_id=sell_signal.signal_id,
            status="CONFIRMED",
            tx_hash=tx_hash,
            actual_amount_sol=sell_quantity * price,
            gas_cost_sol=0.0,
            received_at=received_at,
            confirmed_at=received_at,
        )
        return SellExecutionResult(
            success=True,
            sell_execution=execution.to_dict(),
            order_id=execution_id,
            tx_hash=tx_hash,
            error_message=None,
            gas_cost_sol=0.0,
            actual_slippage_percent=0.0,
            confirmation_time_ms=0.0,
        )
