#!/usr/bin/env python3
"""GMGN 全自动跟单机器人 — 买入 + 卖出 + TP/SL 全自动

功能:
    1. 从白名单配置读取跟单钱包
    2. 监控白名单钱包的买入/卖出活动
    3. 自动跟随买入 (auto_confirm)
    4. 自动跟随卖出 (EXIT/REDUCE 信号)
    5. 自动检测 TP/SL 并执行卖出
    6. 持仓价格持续监控与更新

Usage:
    # 单次运行
    python3 scripts/run_auto_copy_trading.py

    # 指定轮询间隔（秒）持续运行
    python3 scripts/run_auto_copy_trading.py --interval 60

    # 仅执行价格监控和 TP/SL 检测（不获取新信号）
    python3 scripts/run_auto_copy_trading.py --monitor-only
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from gmgn_monitor.audit_log import append_audit_event
from gmgn_monitor.birdeye_client import BirdeyeClient
from gmgn_monitor.config_manager import ConfigManager
from gmgn_monitor.copy_sell_handler import CopySellHandler
from gmgn_monitor.copy_trade_guards import (
    CopyTradeContext,
    CopyTradeGuards,
    demote_leader_in_whitelist,
    load_copy_trade_guard_config,
)
from gmgn_monitor.execution_loop import ExecutionLoopEngine, MarketData
from gmgn_monitor.execution_switch import ExecutionSwitch, TRADE_MODE_DRYRUN, TRADE_MODE_REAL
from gmgn_monitor.gmgn_api_client import GmgnApiClient
from gmgn_monitor.live_signal_fetcher import LiveSignalFetcher
from gmgn_monitor.order_manager import OrderManager
from gmgn_monitor.paper_trade_executor import PaperBuyExecutor, PaperSellExecutor
from gmgn_monitor.portfolio_tracker import PortfolioTracker
from gmgn_monitor.position_monitor import PositionMonitor
from gmgn_monitor.real_trade_executor import RealTradeExecutor
from gmgn_monitor.risk_manager import RiskLimits, RiskManager
from gmgn_monitor.sell_executor import SellExecutor
from gmgn_monitor.sell_trigger import SellTrigger
from gmgn_monitor.trade_signal import TradeSignal
from gmgn_monitor.css_engine import CSSEngine
from gmgn_monitor.signal_preprocessor import SignalPreprocessor


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WHITELIST_PATH = _PROJECT_ROOT / "config" / "wallet_whitelist.json"
GUARD_CONFIG_PATH = _PROJECT_ROOT / "config" / "copy_trade_guards.json"
DATA_DIR = _PROJECT_ROOT / "data"
LOG_DIR = DATA_DIR / "auto_copy_logs"
SELL_COOLDOWN_SECONDS = 30 * 60
COPY_SELL_DEDUP_SECONDS = 3 * 60


def _audit_auto_trade(
    action: str,
    success: bool,
    token_address: str,
    message: str,
    details: dict[str, Any],
    category: str = "auto_trade",
) -> None:
    append_audit_event(
        _PROJECT_ROOT,
        category=category,
        action=action,
        success=success,
        source="run_auto_copy_trading",
        actor="system",
        object_type="token",
        object_id=token_address,
        message=message,
        details=details,
    )


def _signal_details(signal: TradeSignal) -> dict[str, Any]:
    return {
        "signal_id": signal.signal_id,
        "wallet_address": signal.wallet_address,
        "target_token": signal.target_token,
        "signal_type": signal.signal_type,
        "recommended_amount_sol": signal.recommended_amount_sol,
        "confidence_score": signal.confidence_score,
        "quality_score": signal.quality_score,
    }


def _local_position_tokens(portfolio: PortfolioTracker) -> set[str]:
    return {position.token_address for position in portfolio.list_positions()}


def _clone_portfolio(portfolio: PortfolioTracker) -> PortfolioTracker:
    snapshot = portfolio.get_snapshot()
    entry_cost = sum(
        position.entry_price_sol * position.quantity
        for position in snapshot.positions
    )
    clone = PortfolioTracker(initial_balance_sol=snapshot.available_sol + entry_cost)
    for position in snapshot.positions:
        clone.open_position(
            position.token_address,
            entry_price_sol=position.entry_price_sol,
            quantity=position.quantity,
            entry_time=position.entry_time,
        )
        clone.update_price(position.token_address, position.current_price_sol)
    return clone


def _sync_buy_executor_portfolio(components: dict[str, Any]) -> None:
    buy_executor = components.get("buy_executor")
    portfolio = components.get("portfolio")
    if buy_executor is None or portfolio is None:
        return
    if hasattr(buy_executor, "_portfolio"):
        buy_executor._portfolio = _clone_portfolio(portfolio)


def _clear_local_position(
    portfolio: PortfolioTracker,
    sell_trigger: SellTrigger | None,
    token_address: str,
) -> None:
    position = portfolio.get_position(token_address)
    if position is not None:
        portfolio.close_position(token_address, exit_price_sol=position.current_price_sol)
    if sell_trigger is not None:
        sell_trigger.remove_signal(token_address)
        sell_trigger.reset_triggered_levels(token_address)


def _mark_sell_cooldown(
    components: dict[str, Any],
    token_address: str,
    reason: str,
    seconds: int = SELL_COOLDOWN_SECONDS,
) -> None:
    cooldowns = components.setdefault("sell_cooldowns", {})
    cooldowns[token_address] = {
        "until": time.time() + seconds,
        "reason": reason,
    }


def _sell_cooldown_reason(components: dict[str, Any], token_address: str) -> str | None:
    cooldowns = components.setdefault("sell_cooldowns", {})
    record = cooldowns.get(token_address)
    if not isinstance(record, dict):
        return None
    if time.time() >= float(record.get("until") or 0.0):
        cooldowns.pop(token_address, None)
        return None
    return str(record.get("reason") or "cooldown")


def _copy_sell_seen(components: dict[str, Any], signal: TradeSignal) -> bool:
    seen = components.setdefault("copy_sell_seen", {})
    now = time.time()
    for key, expires_at in list(seen.items()):
        if now >= float(expires_at):
            seen.pop(key, None)
    key = f"{signal.wallet_address}:{signal.target_token}:{signal.signal_type}"
    if key in seen:
        return True
    seen[key] = now + COPY_SELL_DEDUP_SECONDS
    return False


def _handle_sell_result_cleanup(
    components: dict[str, Any],
    token_address: str,
    success: bool,
    error_message: str | None,
    sell_percent: float = 100.0,
) -> None:
    portfolio = components["portfolio"]
    sell_trigger = components.get("sell_trigger")
    if success and sell_percent >= 99.9:
        _clear_local_position(portfolio, sell_trigger, token_address)
        _mark_sell_cooldown(components, token_address, "sold", SELL_COOLDOWN_SECONDS)
        return
    if error_message == "Zero token balance":
        _clear_local_position(portfolio, sell_trigger, token_address)
        _mark_sell_cooldown(components, token_address, "zero_balance", SELL_COOLDOWN_SECONDS)


def _cleanup_failed_buy(
    components: dict[str, Any],
    token_address: str,
) -> None:
    _clear_local_position(
        components["portfolio"],
        components.get("sell_trigger"),
        token_address,
    )


def _add_skip(summary: dict[str, int], reason: str) -> None:
    summary[reason] = summary.get(reason, 0) + 1


def _get_wallet_address() -> str:
    """Return the wallet address from environment variable."""
    addr = os.environ.get("GMGN_WALLET_ADDRESS", "")
    if not addr:
        raise ValueError("GMGN_WALLET_ADDRESS environment variable is required")
    return addr

CHAIN = "sol"


def _load_whitelist_config(path: Path) -> dict[str, Any]:
    """Load wallet whitelist configuration."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_follow_wallets(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract wallets with mode='follow' from the whitelist config."""
    wallets = config.get("wallets", [])
    return [w for w in wallets if w.get("mode") == "follow" and w.get("enabled", True)]


def _build_wallet_scores(follow_wallets: list[dict[str, Any]]) -> dict[str, float]:
    """Build a mapping of wallet_address -> score for signal confidence."""
    return {
        w["wallet_address"]: w.get("total_score", 50.0)
        for w in follow_wallets
    }


def _build_risk_limits(
    follow_wallets: list[dict[str, Any]],
    global_settings: dict[str, Any] | None = None,
) -> RiskLimits:
    """Build RiskLimits with tiny_real-safe defaults (no win-driven size scaling)."""
    settings = global_settings or {}
    stop_loss = -40.0
    if follow_wallets:
        stop_loss = float(follow_wallets[0].get("risk_limits", {}).get("stop_loss_percent", -40.0))
    # tiny_real default: 0.03 SOL daily loss on a ~1 SOL working set ≈ 3%.
    daily_loss_percent = float(settings.get("daily_loss_limit_percent", 3.0) or 3.0)
    return RiskLimits(
        daily_loss_limit_percent=daily_loss_percent,
        max_single_position_percent=20.0,
        max_total_positions=min(3, int(settings.get("max_total_positions", 3) or 3)),
        default_stop_loss_percent=stop_loss,
        circuit_breaker_cooldown_seconds=600,
        kill_switch=False,
    )


def _parse_activity_timestamp(entry: dict[str, Any]) -> datetime | None:
    raw = entry.get("timestamp") or entry.get("time") or entry.get("block_time") or entry.get("created_at")
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
        if value > 1_000_000_000_000:
            value /= 1000.0
        return datetime.fromtimestamp(value, tz=timezone.utc)
    text = str(raw).strip()
    if not text:
        return None
    if text.isdigit():
        return _parse_activity_timestamp({"timestamp": int(text)})
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _optional_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def _extract_leader_price(entry: dict[str, Any]) -> float | None:
    for key in ("price", "price_usd", "token_price", "avg_price"):
        price = _optional_float(entry.get(key))
        if price is not None and price > 0:
            return price
    token_info = entry.get("token")
    if isinstance(token_info, dict):
        for key in ("price", "price_usd"):
            price = _optional_float(token_info.get(key))
            if price is not None and price > 0:
                return price
    quote = _optional_float(entry.get("quote_amount"))
    base = _optional_float(entry.get("base_amount") or entry.get("token_amount") or entry.get("amount"))
    if quote is not None and base is not None and base > 0 and quote > 0:
        return quote / base
    return None


def _extract_security_flags(entry: dict[str, Any]) -> dict[str, Any]:
    security = entry.get("security") if isinstance(entry.get("security"), dict) else {}
    token_info = entry.get("token") if isinstance(entry.get("token"), dict) else {}
    source = {**token_info, **security, **entry}
    return {
        "honeypot_risk": _optional_bool(source.get("honeypot_risk") if "honeypot_risk" in source else source.get("is_honeypot")),
        "lp_burned_or_locked": _optional_bool(
            source.get("lp_burned_or_locked")
            if "lp_burned_or_locked" in source
            else source.get("is_burna_lp") if "is_burna_lp" in source else source.get("lp_locked")
        ),
        "top10_holder_percent": _optional_float(
            source.get("top10_holder_percent")
            if "top10_holder_percent" in source
            else source.get("top_10_holder_rate")
        ),
        "mint_authority_active": _optional_bool(
            source.get("mint_authority_active")
            if "mint_authority_active" in source
            else source.get("is_mintable")
        ),
        "freeze_authority_active": _optional_bool(
            source.get("freeze_authority_active")
            if "freeze_authority_active" in source
            else source.get("is_freezable")
        ),
    }


def _build_copy_context(
    entry: dict[str, Any],
    *,
    amount_sol: float,
    expected_entry_price: float | None = None,
) -> CopyTradeContext:
    flags = _extract_security_flags(entry)
    leader_price = _extract_leader_price(entry)
    expected = expected_entry_price
    if expected is None:
        expected = _optional_float(entry.get("current_price") or entry.get("mark_price"))
    return CopyTradeContext(
        leader_entry_price=leader_price,
        expected_entry_price=expected,
        leader_traded_at=_parse_activity_timestamp(entry),
        amount_sol=amount_sol,
        honeypot_risk=flags["honeypot_risk"],
        lp_burned_or_locked=flags["lp_burned_or_locked"],
        top10_holder_percent=flags["top10_holder_percent"],
        mint_authority_active=flags["mint_authority_active"],
        freeze_authority_active=flags["freeze_authority_active"],
    )


def _apply_buy_guards(
    components: dict[str, Any],
    signals: list[TradeSignal],
) -> tuple[list[TradeSignal], dict[str, int]]:
    guards: CopyTradeGuards = components["copy_guards"]
    contexts: dict[str, CopyTradeContext] = components.setdefault("signal_contexts", {})
    skipped: dict[str, int] = {}
    accepted: list[TradeSignal] = []
    for signal in signals:
        if signal.signal_type not in ("NEW_POSITION", "ADD_POSITION"):
            accepted.append(signal)
            continue
        context = contexts.get(signal.signal_id) or CopyTradeContext(
            amount_sol=signal.recommended_amount_sol,
        )
        decision = guards.evaluate_buy(signal.wallet_address, context)
        if not decision.allow:
            _add_skip(skipped, decision.reason or "guard_block")
            continue
        accepted.append(signal)
    return accepted, skipped


def _apply_pending_demotions(components: dict[str, Any]) -> list[dict[str, str]]:
    guards: CopyTradeGuards = components["copy_guards"]
    whitelist_path = Path(components.get("whitelist_path") or WHITELIST_PATH)
    applied: list[dict[str, str]] = []
    for item in guards.drain_demotions():
        wallet = item["wallet_address"]
        reason = item["reason"]
        changed = demote_leader_in_whitelist(
            whitelist_path,
            wallet,
            reason=reason,
            demote_mode=guards.config.demote_mode,
        )
        if changed:
            applied.append(item)
            print(f"[Guard] Demoted leader {wallet[:8]}... ({reason})")
            _audit_auto_trade(
                "leader_demote",
                True,
                wallet,
                reason,
                {"wallet_address": wallet, "reason": reason},
                category="manual_config",
            )
    if applied:
        _refresh_follow_config(components)
    return applied


def _refresh_follow_config(components: dict[str, Any]) -> list[dict[str, Any]]:
    """Reload the active follow list so long-running workers do not use stale leaders."""
    whitelist_path = Path(components.get("whitelist_path") or WHITELIST_PATH)
    config = _load_whitelist_config(whitelist_path)
    follow_wallets = _get_follow_wallets(config)
    wallet_scores = _build_wallet_scores(follow_wallets)
    global_settings = config.get("global_settings") if isinstance(config.get("global_settings"), dict) else {}
    risk_limits = _build_risk_limits(follow_wallets, global_settings)

    old_addresses = _current_follow_wallet_addresses(components)
    components["follow_wallets"] = follow_wallets
    components["wallet_scores"] = wallet_scores
    components["risk_limits"] = risk_limits

    signal_fetcher = components.get("signal_fetcher")
    if signal_fetcher is not None:
        signal_fetcher.wallet_scores = wallet_scores

    risk_manager = components.get("risk_manager")
    if risk_manager is not None:
        risk_manager.risk_limits = risk_limits

    buy_executor = components.get("buy_executor")
    if buy_executor is not None and hasattr(buy_executor, "_risk_limits"):
        buy_executor._risk_limits = risk_limits
    if buy_executor is not None and hasattr(buy_executor, "_risk_manager"):
        buy_executor._risk_manager = RiskManager(risk_limits)

    new_addresses = _current_follow_wallet_addresses(components)
    removed_addresses = old_addresses - new_addresses
    if old_addresses != new_addresses:
        print(
            "[Config] Follow wallets reloaded: "
            f"{len(old_addresses)} -> {len(new_addresses)}"
        )
    if removed_addresses and components.get("liquidate_removed_leaders", True):
        for removed_address in sorted(removed_addresses):
            try:
                from gmgn_monitor.dashboard import _liquidate_leader_positions
                result = _liquidate_leader_positions(
                    _PROJECT_ROOT,
                    removed_address,
                    "Leader 已从跟单白名单移除，自动平仓该 Leader 跟单持仓",
                )
                print(
                    "[Config] Removed leader liquidation: "
                    f"{removed_address[:8]}... matched={result.get('matched_positions', 0)}"
                )
            except Exception as exc:
                print(f"[Config WARN] Removed leader liquidation failed for {removed_address[:8]}...: {exc}")
    return follow_wallets


def _current_follow_wallet_addresses(components: dict[str, Any]) -> set[str]:
    return {
        str(wallet.get("wallet_address") or "")
        for wallet in components.get("follow_wallets", [])
        if wallet.get("wallet_address")
    }


def _filter_current_follow_signals(
    components: dict[str, Any],
    signals: list[TradeSignal],
) -> list[TradeSignal]:
    allowed_wallets = _current_follow_wallet_addresses(components)
    if not allowed_wallets:
        return []
    return [signal for signal in signals if signal.wallet_address in allowed_wallets]


def _resolve_trade_mode(config: dict[str, Any], explicit: str | None = None) -> str:
    if explicit:
        return ExecutionSwitch(explicit).mode
    cfg_mode = str(config.get("trade_mode") or "").strip().lower()
    if cfg_mode in (TRADE_MODE_DRYRUN, TRADE_MODE_REAL):
        return cfg_mode
    return ExecutionSwitch().mode


def _init_components(
    config: dict[str, Any],
    api_key: str | None,
    private_key_pem: str | None,
    wallet_address: str | None = None,
    *,
    trade_mode: str | None = None,
) -> dict[str, Any]:
    """Initialize all trading components."""
    mode = _resolve_trade_mode(config, trade_mode)
    paper_mode = mode == TRADE_MODE_DRYRUN
    if paper_mode:
        wallet_address = wallet_address or os.environ.get("GMGN_WALLET_ADDRESS") or "PaperWallet1111111111111111111111111111111"
    else:
        wallet_address = wallet_address or _get_wallet_address()
    follow_wallets = _get_follow_wallets(config)
    wallet_scores = _build_wallet_scores(follow_wallets)
    global_settings = config.get("global_settings") if isinstance(config.get("global_settings"), dict) else {}
    risk_limits = _build_risk_limits(follow_wallets, global_settings)
    copy_guards = CopyTradeGuards(config=load_copy_trade_guard_config(GUARD_CONFIG_PATH))

    # Core components
    order_manager = OrderManager()
    portfolio = PortfolioTracker(initial_balance_sol=10.0)
    risk_manager = RiskManager(risk_limits)
    css_engine = CSSEngine()
    preprocessor = SignalPreprocessor()

    gmgn_client = None
    signal_fetcher = None
    if api_key:
        gmgn_client = GmgnApiClient(api_key=api_key, private_key_pem=private_key_pem or "")
        signal_fetcher = LiveSignalFetcher(api_client=gmgn_client, wallet_scores=wallet_scores)

    # Price monitoring (best-effort; paper mode tolerates failures)
    birdeye = BirdeyeClient()
    position_monitor = PositionMonitor(birdeye_client=birdeye)

    if paper_mode:
        buy_executor = PaperBuyExecutor(portfolio=portfolio)
        sell_executor = PaperSellExecutor(portfolio=portfolio)
    else:
        if not api_key or not private_key_pem:
            raise ValueError("real mode requires GMGN_API_KEY and private key")
        buy_executor = RealTradeExecutor(
            wallet_address=wallet_address,
            chain=CHAIN,
            auto_confirm=True,
            api_key=api_key,
            private_key_pem=private_key_pem,
            risk_limits=risk_limits,
        )
        sell_executor = SellExecutor(
            wallet_address=wallet_address,
            chain=CHAIN,
            api_key=api_key,
            private_key_pem=private_key_pem,
            risk_manager=risk_manager,
            order_manager=order_manager,
            portfolio_tracker=portfolio,
            auto_confirm=True,
        )

    sell_trigger = SellTrigger()
    copy_sell_handler = CopySellHandler(sell_executor)  # type: ignore[arg-type]

    # Execution loop (no sell/position_monitor — those are handled in _run_cycle)
    loop = ExecutionLoopEngine(
        css_engine=css_engine,
        preprocessor=preprocessor,
        risk_manager=risk_manager,
        order_manager=order_manager,
        portfolio_tracker=portfolio,
        market_data=MarketData(),
        sell_trigger=sell_trigger,
    )

    return {
        "wallet_address": wallet_address,
        "trade_mode": mode,
        "paper_mode": paper_mode,
        "follow_wallets": follow_wallets,
        "wallet_scores": wallet_scores,
        "risk_limits": risk_limits,
        "order_manager": order_manager,
        "portfolio": portfolio,
        "risk_manager": risk_manager,
        "position_monitor": position_monitor,
        "buy_executor": buy_executor,
        "sell_executor": sell_executor,
        "sell_trigger": sell_trigger,
        "copy_sell_handler": copy_sell_handler,
        "loop": loop,
        "signal_fetcher": signal_fetcher,
        "gmgn_client": gmgn_client,
        "copy_guards": copy_guards,
        "signal_contexts": {},
        "liquidate_removed_leaders": not paper_mode,
        "sell_cooldowns": {},
        "copy_sell_seen": {},
        "use_paper_signals": paper_mode and signal_fetcher is None,
    }


def _paper_activity_entries(wallet_address: str, iteration: int) -> list[dict[str, Any]]:
    """Synthetic leader activity for paper mode when live API is unavailable."""
    now = datetime.now(timezone.utc).isoformat()
    token = f"PaperToken{wallet_address[:4]}{iteration % 97:02d}1111111111111111111111"[:44]
    leader_price = 0.001 + (iteration % 5) * 0.0001
    return [
        {
            "event_type": "buy",
            "timestamp": now,
            "quote_amount": 0.01,
            "base_amount": 0.01 / leader_price,
            "price": leader_price,
            "current_price": leader_price * 1.02,
            "token": {"address": token},
            "honeypot_risk": False,
            "lp_locked": True,
            "top10_holder_percent": 18.0,
            "is_mintable": False,
            "is_freezable": False,
        }
    ]


def _fetch_signals(components: dict[str, Any]) -> list[TradeSignal]:
    """Fetch buy/sell signals from followed wallets and attach guard contexts."""
    fetcher = components["signal_fetcher"]
    follow_wallets = components["follow_wallets"]
    wallet_scores = components["wallet_scores"]
    guards: CopyTradeGuards = components["copy_guards"]
    contexts: dict[str, CopyTradeContext] = components.setdefault("signal_contexts", {})
    contexts.clear()

    print(f"[Signal] Fetching activity for {len(follow_wallets)} follow wallets...")

    all_signals: list[TradeSignal] = []
    paper_iteration = int(components.get("paper_iteration") or 0)
    for wallet in follow_wallets:
        addr = wallet["wallet_address"]
        entries: list[Any] = []
        if fetcher is not None:
            try:
                activity = fetcher.api_client.get_wallet_activity(
                    chain=CHAIN, wallet_address=addr, limit=20
                )
                raw_entries = activity.get("activities") or activity.get("data") or []
                if isinstance(raw_entries, dict):
                    raw_entries = raw_entries.get("activities") or raw_entries.get("data") or []
                if isinstance(raw_entries, list):
                    entries = raw_entries
            except Exception as exc:
                print(f"  [WARN] Failed to fetch activity for {addr[:16]}...: {exc}")
                entries = []
        if not entries and components.get("use_paper_signals"):
            entries = _paper_activity_entries(addr, paper_iteration)
            print(f"  [Paper] Synthetic activity for {addr[:8]}... ({len(entries)} entries)")
        if not isinstance(entries, list) or not entries:
            continue

        score = wallet_scores.get(addr, 50.0)
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            action = str(entry.get("event_type", "")).lower()
            if action not in ("buy", "sell"):
                continue

            try:
                token_info = entry.get("token", {})
                token = str(token_info.get("address", "")) if isinstance(token_info, dict) else str(entry.get("token_address", ""))
                # quote_amount is the SOL amount spent/received
                amount = float(entry.get("quote_amount", 0.0))
                if amount <= 0:
                    amount = float(entry.get("amount", 0.0))
                if not token or amount <= 0:
                    continue

                # Determine signal type
                if action == "sell":
                    signal_type = "EXIT"
                else:
                    signal_type = "NEW_POSITION"

                # Build risk config from wallet
                risk_limits = wallet.get("risk_limits", {})
                from gmgn_monitor.trade_signal import TPOrder, SLOrder
                tp_steps = risk_limits.get("take_profit_steps", [])
                tp_orders = tuple(
                    TPOrder(level=i + 1, trigger_percent=s["price_change_percent"], sell_percent=s["sell_percent"])
                    for i, s in enumerate(tp_steps)
                )
                sl_order = SLOrder(
                    trigger_percent=risk_limits.get("stop_loss_percent", -40.0),
                    sell_percent=100.0,
                )

                wallet_cap = float(risk_limits.get("max_single_trade_sol", 0.005) or 0.005)
                sized_amount = min(amount, wallet_cap, guards.config.max_single_trade_sol)
                traded_at = _parse_activity_timestamp(entry)
                expires_at = None
                if traded_at is not None:
                    from datetime import timedelta
                    # TradeSignal.is_expired() compares against naive utcnow().
                    traded_naive = traded_at.astimezone(timezone.utc).replace(tzinfo=None)
                    expires_at = traded_naive + timedelta(seconds=guards.config.max_signal_age_seconds)

                signal = TradeSignal(
                    signal_id=f"auto-{addr[:8]}-{token[:8]}-{int(time.time()*1000)}-{len(all_signals)}",
                    wallet_address=addr,
                    target_token=token,
                    signal_type=signal_type,
                    urgency_score=int(min(100.0, score)),
                    confidence_score=70,
                    quality_score=int(min(100.0, score)),
                    recommended_amount_sol=sized_amount,
                    max_slippage_percent=risk_limits.get("slippage_percent", 2.0),
                    priority_fee_sol=0.01,
                    mev_protection="SECURE",
                    tp_orders=tp_orders,
                    sl_order=sl_order,
                    expires_at=expires_at,
                    chain=CHAIN,
                )
                contexts[signal.signal_id] = _build_copy_context(entry, amount_sol=sized_amount)
                all_signals.append(signal)
            except (ValueError, TypeError, KeyError):
                continue

    print(f"[Signal] Found {len(all_signals)} signals")
    return all_signals


def _record_leader_pnl(
    components: dict[str, Any],
    wallet_address: str,
    token_address: str,
) -> None:
    """Record realized-ish PnL for consecutive-loss demotion using open mark."""
    if not wallet_address:
        return
    portfolio: PortfolioTracker = components["portfolio"]
    position = portfolio.get_position(token_address)
    if position is None:
        return
    pnl = float(getattr(position, "unrealized_pnl_sol", 0.0) or 0.0)
    guards: CopyTradeGuards = components["copy_guards"]
    guards.record_copy_outcome(wallet_address, pnl)


def _run_cycle(components: dict[str, Any], signals: list[TradeSignal]) -> dict[str, Any]:
    """Run one full execution cycle: sells first, then guarded buys."""
    signals = _filter_current_follow_signals(components, signals)
    buy_signals, buy_guard_skips = _apply_buy_guards(components, signals)
    loop = components["loop"]
    buy_executor = components["buy_executor"]
    sell_executor = components["sell_executor"]
    sell_trigger = components["sell_trigger"]
    position_monitor = components["position_monitor"]
    copy_sell_handler = components["copy_sell_handler"]
    portfolio = components["portfolio"]
    wallet_scores = components["wallet_scores"]
    guards: CopyTradeGuards = components["copy_guards"]

    # Step 1: refresh marks so sell decisions and PnL demotion use current prices.
    if position_monitor and portfolio.list_positions():
        try:
            position_monitor.update_portfolio_prices(portfolio)
        except Exception as exc:
            print(f"  [Price Monitor ERROR] {exc}")

    # Step 2: copy-sell first so exits beat new entries.
    copy_sell_results = []
    copy_sell_skipped_summary: dict[str, int] = {}
    if copy_sell_handler:
        for signal in signals:
            if signal.signal_type not in ("EXIT", "REDUCE"):
                continue
            cooldown_reason = _sell_cooldown_reason(components, signal.target_token)
            if cooldown_reason is not None:
                _add_skip(copy_sell_skipped_summary, cooldown_reason)
                continue
            if _copy_sell_seen(components, signal):
                _add_skip(copy_sell_skipped_summary, "duplicate_signal")
                continue
            try:
                if signal.signal_type == "EXIT":
                    _record_leader_pnl(components, signal.wallet_address, signal.target_token)
                sell_result = copy_sell_handler.handle_signal(signal)
                if sell_result:
                    result_payload = sell_result.to_dict()
                    _handle_sell_result_cleanup(
                        components,
                        signal.target_token,
                        bool(sell_result.success),
                        sell_result.error_message,
                        100.0 if signal.signal_type == "EXIT" else 50.0,
                    )
                    copy_sell_results.append({
                        "signal": _signal_details(signal),
                        "result": result_payload,
                    })
                    _audit_auto_trade(
                        "auto_copy_sell",
                        bool(sell_result.success),
                        signal.target_token,
                        str(sell_result.error_message or "自动跟卖已处理"),
                        {
                            "signal": _signal_details(signal),
                            "result": result_payload,
                        },
                        category="copy_trade",
                    )
                    print(f"  [Copy Sell] {signal.target_token[:8]}... success={sell_result.success}")
            except Exception as exc:
                print(f"  [Copy Sell ERROR] {signal.target_token[:8]}...: {exc}")
                _audit_auto_trade(
                    "auto_copy_sell",
                    False,
                    signal.target_token,
                    str(exc),
                    {
                        "signal": _signal_details(signal),
                        "error": str(exc),
                    },
                    category="copy_trade",
                )

    # Step 3: TP / SL trigger detection and execution
    sell_signals = []
    sell_results = []
    if sell_trigger and portfolio.list_positions():
        raw_sell_signals = sell_trigger.scan_all_positions(portfolio)
        sell_signals = [s.to_dict() for s in raw_sell_signals]
        for raw_signal in raw_sell_signals:
            try:
                sell_result = sell_executor.execute_sell(raw_signal)
                result_payload = sell_result.to_dict()
                _handle_sell_result_cleanup(
                    components,
                    raw_signal.token_address,
                    bool(sell_result.success),
                    sell_result.error_message,
                    raw_signal.sell_percent,
                )
                sell_results.append({
                    "signal": raw_signal.to_dict(),
                    "result": result_payload,
                })
                if sell_result.success and raw_signal.sell_percent >= 99.9:
                    sell_trigger.remove_signal(raw_signal.token_address)
                _audit_auto_trade(
                    "auto_tpsl_sell",
                    bool(sell_result.success),
                    raw_signal.token_address,
                    str(sell_result.error_message or "自动止盈止损卖出已处理"),
                    {
                        "signal": raw_signal.to_dict(),
                        "result": result_payload,
                    },
                )
                print(f"  [TP/SL Sell] {raw_signal.token_address[:8]}... success={sell_result.success}")
            except Exception as exc:
                print(f"  [TP/SL Sell ERROR] {raw_signal.token_address[:8]}...: {exc}")
                _audit_auto_trade(
                    "auto_tpsl_sell",
                    False,
                    raw_signal.token_address,
                    str(exc),
                    {
                        "signal": raw_signal.to_dict(),
                        "error": str(exc),
                    },
                )

    demotions = _apply_pending_demotions(components)

    # Step 4: guarded buys only after exits.
    _sync_buy_executor_portfolio(components)
    result = loop.run_cycle(buy_signals, wallet_scores)

    buy_executed = []
    for order_info in result.get("orders_created", []):
        signal = next((s for s in buy_signals if s.signal_id == order_info.get("signal_id")), None)
        if signal is None:
            continue
        try:
            trade_result = buy_executor.execute_trade(signal)
            buy_executed.append({
                "order_id": order_info.get("order_id"),
                "signal_id": signal.signal_id,
                "token": signal.target_token,
                "success": trade_result.success,
                "tx_hash": trade_result.tx_hash,
                "error": trade_result.error_message,
            })
            if trade_result.success:
                guards.reserve_exposure(signal.wallet_address, signal.recommended_amount_sol)
            else:
                _cleanup_failed_buy(components, signal.target_token)
            _audit_auto_trade(
                "auto_buy",
                bool(trade_result.success),
                signal.target_token,
                str(trade_result.error_message or "自动买入已提交"),
                {
                    "order_id": order_info.get("order_id"),
                    "tx_hash": trade_result.tx_hash,
                    "signal": _signal_details(signal),
                    "error": trade_result.error_message,
                },
            )
            print(f"  [Buy] {signal.target_token[:8]}... success={trade_result.success} tx={trade_result.tx_hash}")
        except Exception as exc:
            print(f"  [Buy ERROR] {signal.target_token[:8]}...: {exc}")
            buy_executed.append({
                "order_id": order_info.get("order_id"),
                "signal_id": signal.signal_id,
                "token": signal.target_token,
                "success": False,
                "error": str(exc),
            })
            _cleanup_failed_buy(components, signal.target_token)
            _audit_auto_trade(
                "auto_buy",
                False,
                signal.target_token,
                str(exc),
                {
                    "order_id": order_info.get("order_id"),
                    "signal": _signal_details(signal),
                    "error": str(exc),
                },
            )

    print(f"[Cycle] Buy signals: {result['processed_count']}")
    print(f"[Cycle] Buy guards skipped: {sum(buy_guard_skips.values())} {buy_guard_skips}")
    print(f"[Cycle] Orders created: {len(result['orders_created'])}")
    print(f"[Cycle] Buy executed: {len([b for b in buy_executed if b['success']])}/{len(buy_executed)}")
    print(f"[Cycle] Copy sells: {len(copy_sell_results)} executed, {sum(copy_sell_skipped_summary.values())} skipped")
    print(f"[Cycle] TP/SL sells: {len(sell_results)}")
    print(f"[Cycle] Leader demotions: {len(demotions)}")
    print(f"[Cycle] Duration: {result['cycle_duration_ms']:.0f} ms")

    result["buy_executed"] = buy_executed
    result["buy_guard_skips"] = buy_guard_skips
    result["copy_sell_results"] = copy_sell_results
    result["copy_sell_skipped_summary"] = copy_sell_skipped_summary
    result["sell_signals"] = sell_signals
    result["sell_results"] = sell_results
    result["leader_demotions"] = demotions
    return result


def _log_cycle(result: dict[str, Any]) -> None:
    """Append cycle result to a daily JSONL log."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    log_path = LOG_DIR / f"auto_copy_{today}.jsonl"
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "processed_count": result.get("processed_count", 0),
        "orders_created": len(result.get("orders_created", [])),
        "orders": result.get("orders_created", []),
        "buy_executed": result.get("buy_executed", []),
        "buy_guard_skips": result.get("buy_guard_skips", {}),
        "copy_sell_results": result.get("copy_sell_results", []),
        "copy_sell_skipped_summary": result.get("copy_sell_skipped_summary", {}),
        "sell_signals": len(result.get("sell_signals", [])),
        "sell_signal_details": result.get("sell_signals", []),
        "sell_results": len(result.get("sell_results", [])),
        "sell_result_details": result.get("sell_results", []),
        "leader_demotions": result.get("leader_demotions", []),
        "cycle_duration_ms": result.get("cycle_duration_ms", 0),
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _main_loop(components: dict[str, Any], interval: int, monitor_only: bool) -> None:
    """Main loop: fetch signals → execute → wait → repeat."""
    wallet_address = components.get("wallet_address") or _get_wallet_address()
    paper_mode = bool(components.get("paper_mode"))
    print("=" * 60)
    print("GMGN 全自动跟单机器人")
    print("=" * 60)
    print(f"Wallet: {wallet_address}")
    print(f"Chain: {CHAIN}")
    print(f"Trade mode: {components.get('trade_mode')} ({'PAPER — no chain orders' if paper_mode else 'REAL MONEY'})")
    print(f"Auto-confirm: ENABLED")
    print(f"Follow wallets: {len(components['follow_wallets'])}")
    print(f"Mode: {'Monitor-only' if monitor_only else 'Full auto'}")
    print(f"Interval: {interval}s")
    print("=" * 60)

    iteration = 0
    while True:
        iteration += 1
        components["paper_iteration"] = iteration
        now = datetime.now(timezone.utc).isoformat()
        print(f"\n--- Iteration #{iteration} @ {now} ---")

        try:
            if monitor_only:
                # Only update prices and check TP/SL
                signals: list[TradeSignal] = []
            else:
                _refresh_follow_config(components)
                signals = _fetch_signals(components)

            result = _run_cycle(components, signals)
            _log_cycle(result)
            if paper_mode:
                snapshot = components["portfolio"].get_snapshot().to_dict()
                open_count = len(snapshot.get("positions") or [])
                print(
                    "[Paper] portfolio "
                    f"value={snapshot.get('total_value_sol')} "
                    f"open={open_count} "
                    f"pnl={snapshot.get('daily_pnl_sol')} "
                    f"available={snapshot.get('available_sol')}"
                )

        except Exception as exc:
            print(f"[ERROR] Iteration failed: {exc}")
            import traceback
            traceback.print_exc()

        if interval <= 0:
            print("\nSingle-run mode complete. Exiting.")
            break

        print(f"[Sleep] Waiting {interval}s...")
        time.sleep(interval)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="run_auto_copy_trading.py",
        description="GMGN Fully Automated Copy Trading Bot",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=0,
        help="Polling interval in seconds (0 = single run, default: 0)",
    )
    parser.add_argument(
        "--monitor-only",
        action="store_true",
        default=False,
        help="Only monitor prices and TP/SL, do not fetch new buy signals",
    )
    parser.add_argument(
        "--whitelist",
        type=str,
        default=str(WHITELIST_PATH),
        help="Path to wallet whitelist JSON",
    )
    parser.add_argument(
        "--wallet",
        type=str,
        default=None,
        help="Your Solana wallet address (defaults to GMGN_WALLET_ADDRESS env var)",
    )
    parser.add_argument(
        "--paper",
        action="store_true",
        default=False,
        help="Force paper/dryrun mode (no chain orders)",
    )
    parser.add_argument(
        "--trade-mode",
        choices=[TRADE_MODE_DRYRUN, TRADE_MODE_REAL],
        default=None,
        help="Override trade mode (defaults to whitelist/env/exposure_state)",
    )
    args = parser.parse_args()

    # Load credentials
    cfg = ConfigManager()
    api_key = cfg.gmgn_api_key
    private_key = cfg.gmgn_private_key

    # Load whitelist
    whitelist_path = Path(args.whitelist)
    if not whitelist_path.exists():
        print(f"[ERROR] Whitelist not found: {whitelist_path}")
        return 1
    config = _load_whitelist_config(whitelist_path)
    trade_mode = TRADE_MODE_DRYRUN if args.paper else args.trade_mode
    resolved_mode = _resolve_trade_mode(config, trade_mode)

    if resolved_mode == TRADE_MODE_REAL:
        if not api_key:
            print("[ERROR] GMGN_API_KEY not configured. Set env var or config.")
            return 1
        if not private_key:
            print("[ERROR] GMGN private key not found. Ensure ~/.config/gmgn/keypair.pem exists.")
            return 1
    elif not api_key:
        print("[Paper] GMGN_API_KEY missing — using synthetic leader activity until API is configured.")

    # Initialize components
    components = _init_components(
        config,
        api_key,
        private_key,
        wallet_address=args.wallet,
        trade_mode=resolved_mode,
    )
    components["whitelist_path"] = whitelist_path
    print(
        f"[Init] Components loaded: {len(components['follow_wallets'])} follow wallets "
        f"(mode={components['trade_mode']})"
    )

    # Run main loop
    _main_loop(components, interval=args.interval, monitor_only=args.monitor_only)
    return 0


if __name__ == "__main__":
    sys.exit(main())
