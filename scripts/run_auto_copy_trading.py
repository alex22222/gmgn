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
from gmgn_monitor.execution_loop import ExecutionLoopEngine, MarketData
from gmgn_monitor.gmgn_api_client import GmgnApiClient
from gmgn_monitor.live_signal_fetcher import LiveSignalFetcher
from gmgn_monitor.order_manager import OrderManager
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


def _build_risk_limits(follow_wallets: list[dict[str, Any]]) -> RiskLimits:
    """Build RiskLimits from the first wallet's risk config (or defaults)."""
    if follow_wallets:
        r = follow_wallets[0].get("risk_limits", {})
        return RiskLimits(
            daily_loss_limit_percent=5.0,
            max_single_position_percent=20.0,
            max_total_positions=3,
            default_stop_loss_percent=r.get("stop_loss_percent", -40.0),
            circuit_breaker_cooldown_seconds=600,
            kill_switch=False,
        )
    return RiskLimits(
        daily_loss_limit_percent=5.0,
        max_single_position_percent=20.0,
        max_total_positions=3,
        default_stop_loss_percent=-40.0,
    )


def _refresh_follow_config(components: dict[str, Any]) -> list[dict[str, Any]]:
    """Reload the active follow list so long-running workers do not use stale leaders."""
    whitelist_path = Path(components.get("whitelist_path") or WHITELIST_PATH)
    config = _load_whitelist_config(whitelist_path)
    follow_wallets = _get_follow_wallets(config)
    wallet_scores = _build_wallet_scores(follow_wallets)
    risk_limits = _build_risk_limits(follow_wallets)

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


def _init_components(
    config: dict[str, Any],
    api_key: str,
    private_key_pem: str,
    wallet_address: str | None = None,
) -> dict[str, Any]:
    """Initialize all trading components."""
    wallet_address = wallet_address or _get_wallet_address()
    follow_wallets = _get_follow_wallets(config)
    wallet_scores = _build_wallet_scores(follow_wallets)
    risk_limits = _build_risk_limits(follow_wallets)

    # Core components
    order_manager = OrderManager()
    portfolio = PortfolioTracker(initial_balance_sol=10.0)
    risk_manager = RiskManager(risk_limits)
    css_engine = CSSEngine()
    preprocessor = SignalPreprocessor()

    # GMGN API client (shared)
    gmgn_client = GmgnApiClient(api_key=api_key, private_key_pem=private_key_pem)

    # Price monitoring
    birdeye = BirdeyeClient()
    position_monitor = PositionMonitor(birdeye_client=birdeye)

    # Real-money executors (auto_confirm=True for fully automated trading)
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
    copy_sell_handler = CopySellHandler(sell_executor)

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

    # Signal fetcher
    signal_fetcher = LiveSignalFetcher(api_client=gmgn_client, wallet_scores=wallet_scores)

    return {
        "wallet_address": wallet_address,
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
        "liquidate_removed_leaders": True,
        "sell_cooldowns": {},
        "copy_sell_seen": {},
    }


def _fetch_signals(components: dict[str, Any]) -> list[TradeSignal]:
    """Fetch buy signals from followed wallets."""
    fetcher = components["signal_fetcher"]
    follow_wallets = components["follow_wallets"]
    wallet_scores = components["wallet_scores"]

    print(f"[Signal] Fetching activity for {len(follow_wallets)} follow wallets...")

    all_signals: list[TradeSignal] = []
    for wallet in follow_wallets:
        addr = wallet["wallet_address"]
        try:
            activity = fetcher.api_client.get_wallet_activity(
                chain=CHAIN, wallet_address=addr, limit=20
            )
        except Exception as exc:
            print(f"  [WARN] Failed to fetch activity for {addr[:16]}...: {exc}")
            continue

        entries = activity.get("activities") or activity.get("data") or []
        if isinstance(entries, dict):
            entries = entries.get("activities") or entries.get("data") or []
        if not isinstance(entries, list):
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
                tp_steps = risk_limits.get("take_profit_steps", [])
                from gmgn_monitor.trade_signal import TPOrder, SLOrder
                tp_orders = tuple(
                    TPOrder(level=i + 1, trigger_percent=s["price_change_percent"], sell_percent=s["sell_percent"])
                    for i, s in enumerate(tp_steps)
                )
                sl_order = SLOrder(
                    trigger_percent=risk_limits.get("stop_loss_percent", -40.0),
                    sell_percent=100.0,
                )

                signal = TradeSignal(
                    signal_id=f"auto-{addr[:8]}-{token[:8]}-{int(time.time())}",
                    wallet_address=addr,
                    target_token=token,
                    signal_type=signal_type,
                    urgency_score=int(min(100.0, score)),
                    confidence_score=70,
                    quality_score=int(min(100.0, score)),
                    recommended_amount_sol=min(amount, risk_limits.get("max_single_trade_sol", 0.005)),
                    max_slippage_percent=risk_limits.get("slippage_percent", 2.0),
                    priority_fee_sol=0.01,
                    mev_protection="SECURE",
                    tp_orders=tp_orders,
                    sl_order=sl_order,
                    chain=CHAIN,
                )
                all_signals.append(signal)
            except (ValueError, TypeError, KeyError):
                continue

    print(f"[Signal] Found {len(all_signals)} signals")
    return all_signals


def _run_cycle(components: dict[str, Any], signals: list[TradeSignal]) -> dict[str, Any]:
    """Run one full execution cycle (buy + sell)."""
    signals = _filter_current_follow_signals(components, signals)
    loop = components["loop"]
    buy_executor = components["buy_executor"]
    sell_executor = components["sell_executor"]
    sell_trigger = components["sell_trigger"]
    position_monitor = components["position_monitor"]
    copy_sell_handler = components["copy_sell_handler"]
    portfolio = components["portfolio"]
    wallet_scores = components["wallet_scores"]

    # Step 1: signal filtering and decision-making
    result = loop.run_cycle(signals, wallet_scores)

    # Step 2: execute real buy trades for each created order
    buy_executed = []
    for order_info in result.get("orders_created", []):
        signal = next((s for s in signals if s.signal_id == order_info.get("signal_id")), None)
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
            if not trade_result.success:
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

    # Step 3: update position prices (skip if no positions)
    price_updates = []
    if position_monitor and portfolio.list_positions():
        try:
            price_updates = position_monitor.update_portfolio_prices(portfolio)
        except Exception as exc:
            print(f"  [Price Monitor ERROR] {exc}")

    # Step 4: copy-sell signal handling (EXIT / REDUCE)
    copy_sell_results = []
    copy_sell_skipped_summary: dict[str, int] = {}
    if copy_sell_handler:
        for signal in signals:
            if signal.signal_type in ("EXIT", "REDUCE"):
                cooldown_reason = _sell_cooldown_reason(components, signal.target_token)
                if cooldown_reason is not None:
                    _add_skip(copy_sell_skipped_summary, cooldown_reason)
                    continue
                if _copy_sell_seen(components, signal):
                    _add_skip(copy_sell_skipped_summary, "duplicate_signal")
                    continue
                try:
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

    # Step 5: TP / SL trigger detection and execution
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

    # Log summary
    print(f"[Cycle] Buy signals: {result['processed_count']}")
    print(f"[Cycle] Orders created: {len(result['orders_created'])}")
    print(f"[Cycle] Buy executed: {len([b for b in buy_executed if b['success']])}/{len(buy_executed)}")
    print(f"[Cycle] Copy sells: {len(copy_sell_results)} executed, {sum(copy_sell_skipped_summary.values())} skipped")
    print(f"[Cycle] TP/SL sells: {len(sell_results)}")
    print(f"[Cycle] Duration: {result['cycle_duration_ms']:.0f} ms")

    result["buy_executed"] = buy_executed
    result["copy_sell_results"] = copy_sell_results
    result["copy_sell_skipped_summary"] = copy_sell_skipped_summary
    result["sell_signals"] = sell_signals
    result["sell_results"] = sell_results
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
        "copy_sell_results": result.get("copy_sell_results", []),
        "copy_sell_skipped_summary": result.get("copy_sell_skipped_summary", {}),
        "sell_signals": len(result.get("sell_signals", [])),
        "sell_signal_details": result.get("sell_signals", []),
        "sell_results": len(result.get("sell_results", [])),
        "sell_result_details": result.get("sell_results", []),
        "cycle_duration_ms": result.get("cycle_duration_ms", 0),
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _main_loop(components: dict[str, Any], interval: int, monitor_only: bool) -> None:
    """Main loop: fetch signals → execute → wait → repeat."""
    wallet_address = components.get("wallet_address") or _get_wallet_address()
    print("=" * 60)
    print("GMGN 全自动跟单机器人")
    print("=" * 60)
    print(f"Wallet: {wallet_address}")
    print(f"Chain: {CHAIN}")
    print(f"Auto-confirm: ENABLED (FULLY AUTOMATED)")
    print(f"Follow wallets: {len(components['follow_wallets'])}")
    print(f"Mode: {'Monitor-only' if monitor_only else 'Full auto'}")
    print(f"Interval: {interval}s")
    print("=" * 60)

    iteration = 0
    while True:
        iteration += 1
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
    args = parser.parse_args()

    # Load credentials
    cfg = ConfigManager()
    api_key = cfg.gmgn_api_key
    private_key = cfg.gmgn_private_key

    if not api_key:
        print("[ERROR] GMGN_API_KEY not configured. Set env var or config.")
        return 1
    if not private_key:
        print("[ERROR] GMGN private key not found. Ensure ~/.config/gmgn/keypair.pem exists.")
        return 1

    # Load whitelist
    whitelist_path = Path(args.whitelist)
    if not whitelist_path.exists():
        print(f"[ERROR] Whitelist not found: {whitelist_path}")
        return 1
    config = _load_whitelist_config(whitelist_path)

    # Initialize components
    components = _init_components(config, api_key, private_key, wallet_address=args.wallet)
    components["whitelist_path"] = whitelist_path
    print(f"[Init] Components loaded: {len(components['follow_wallets'])} follow wallets")

    # Run main loop
    _main_loop(components, interval=args.interval, monitor_only=args.monitor_only)
    return 0


if __name__ == "__main__":
    sys.exit(main())
