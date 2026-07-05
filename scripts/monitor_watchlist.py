#!/usr/bin/env python3
"""Watchlist Daily Monitor — 观察名单每日监控脚本

功能：
    1. 每日从 GMGN API 获取观察名单钱包的最新 stats
    2. 对比历史 stats，计算变化（利润变化、胜率变化、交易数变化）
    3. 自动升级/降级逻辑：
       - 评分提升 >10 分 或 利润增加 >$500 → 升级到白名单
       - 出现亏损 或 wash_trader 标签 → 降级到黑名单
    4. 生成 JSON 和 Markdown 报告
    5. 通过飞书 webhook 推送报告

Usage:
    python3 scripts/monitor_watchlist.py [--push-feishu]

Cron:
    每天 9:00 CST 执行
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gmgn_monitor.config_manager import ConfigManager
from gmgn_monitor.gmgn_api_client import GmgnApiClient


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_DIR = PROJECT_ROOT / "config"

WATCHLIST_PATH = DATA_DIR / "watchlist_wallets.json"
WHITELIST_PATH = DATA_DIR / "whitelist_wallets.json"
BLACKLIST_PATH = DATA_DIR / "blacklist_wallets.json"
HISTORY_PATH = DATA_DIR / ".watchlist_history.json"
REPORT_JSON_PATH = DATA_DIR / "watchlist_daily_report.json"
REPORT_MD_PATH = DATA_DIR / "watchlist_daily_report.md"
FEISHU_CONFIG_PATH = CONFIG_DIR / "feishu.json"

# Upgrade / downgrade thresholds
SCORE_UPGRADE_THRESHOLD = 10.0       # 评分提升超过此值即升级
PROFIT_UPGRADE_THRESHOLD_USD = 500.0  # 利润增加超过此值即升级
GRADE_UPGRADE_MIN = "C"             # 升级后至少达到 C 级

# Downgrade conditions
DOWGRADE_TAGS = {"wash_trader"}


def load_json_safe(path: Path) -> Any:
    """Load a JSON file, returning None on failure."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def save_json(path: Path, data: Any) -> None:
    """Save data to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_watchlist() -> list[dict]:
    """Load watchlist wallets."""
    data = load_json_safe(WATCHLIST_PATH)
    if not isinstance(data, list):
        print(f"[ERROR] Failed to load watchlist from {WATCHLIST_PATH}")
        return []
    return data


def load_whitelist() -> list[dict]:
    """Load whitelist wallets."""
    data = load_json_safe(WHITELIST_PATH)
    if not isinstance(data, list):
        return []
    return data


def load_blacklist() -> list[dict]:
    """Load blacklist wallets."""
    data = load_json_safe(BLACKLIST_PATH)
    if not isinstance(data, list):
        return []
    return data


def load_history() -> dict:
    """Load historical stats for watchlist wallets."""
    data = load_json_safe(HISTORY_PATH)
    if not isinstance(data, dict):
        return {}
    return data


def save_history(history: dict) -> None:
    """Save historical stats."""
    save_json(HISTORY_PATH, history)


def get_wallet_addresses(wallets: list[dict]) -> list[str]:
    """Extract wallet addresses from a list of wallet dicts."""
    return [w["wallet_address"] for w in wallets if w.get("wallet_address")]


def fetch_wallet_stats(client: GmgnApiClient, addresses: list[str]) -> dict[str, Any]:
    """Fetch wallet stats from GMGN API for a list of addresses.

    The GMGN /v1/user/wallet_stats endpoint only accepts a single wallet
    address per request, so we loop through addresses individually.

    Returns a dict mapping wallet_address → stats dict.
    """
    if not addresses:
        return {}

    results: dict[str, Any] = {}
    for addr in addresses:
        try:
            raw = client.get_wallet_stats(chain="sol", wallet_addresses=[addr], period="7d")
        except Exception as exc:
            print(f"    [WARN] Failed to fetch stats for {addr[:8]}...: {exc}")
            continue

        # Parse the response — it could be a dict with wallet entries
        # or a list of wallet stats
        if isinstance(raw, dict):
            # Try to find wallet data in common keys
            wallets_data = raw.get("wallets") or raw.get("data") or raw
            if isinstance(wallets_data, dict):
                for a, stats in wallets_data.items():
                    results[a] = stats
            elif isinstance(wallets_data, list):
                for entry in wallets_data:
                    if isinstance(entry, dict):
                        a = entry.get("wallet_address") or entry.get("address")
                        if a:
                            results[a] = entry
        elif isinstance(raw, list):
            for entry in raw:
                if isinstance(entry, dict):
                    a = entry.get("wallet_address") or entry.get("address")
                    if a:
                        results[a] = entry

    return results


def extract_stats_for_comparison(wallet: dict, api_stats: dict | None) -> dict:
    """Extract comparable stats from wallet record and/or fresh API data.

    Returns a dict with keys: total_score, realized_profit, winrate,
    total_trades, token_num, avg_holding_hours, wallet_age_days, tags.
    """
    # Start with wallet record data (the baseline)
    stats = {
        "total_score": wallet.get("total_score", 0.0),
        "realized_profit": wallet.get("stats", {}).get("realized_profit", 0.0),
        "winrate": wallet.get("stats", {}).get("winrate", 0.0),
        "total_trades": wallet.get("stats", {}).get("total_trades", 0),
        "token_num": wallet.get("stats", {}).get("token_num", 0),
        "avg_holding_hours": wallet.get("stats", {}).get("avg_holding_hours", 0.0),
        "wallet_age_days": wallet.get("stats", {}).get("wallet_age_days", 0),
        "tags": wallet.get("tags", []),
    }

    # If fresh API data is available, overlay it
    if api_stats and isinstance(api_stats, dict):
        # GMGN API may return data under nested keys
        data = api_stats.get("data") or api_stats
        if isinstance(data, dict):
            # Try various field name mappings
            stats["realized_profit"] = _extract_float(data, [
                "realized_profit", "total_profit", "pnl_usd", "profit_usd"
            ], stats["realized_profit"])
            stats["winrate"] = _extract_float(data, [
                "winrate", "win_rate", "win_rate_percent"
            ], stats["winrate"])
            stats["total_trades"] = int(_extract_float(data, [
                "total_trades", "trades_7d", "trade_count"
            ], float(stats["total_trades"])))
            stats["token_num"] = int(_extract_float(data, [
                "token_num", "tokens_traded", "unique_tokens"
            ], float(stats["token_num"])))
            stats["avg_holding_hours"] = _extract_float(data, [
                "avg_holding_hours", "avg_holding_duration_hours"
            ], stats["avg_holding_hours"])
            stats["wallet_age_days"] = int(_extract_float(data, [
                "wallet_age_days", "age_days"
            ], float(stats["wallet_age_days"])))
            # Tags
            fresh_tags = data.get("tags") or data.get("wallet_tags")
            if isinstance(fresh_tags, list):
                stats["tags"] = fresh_tags
            elif isinstance(fresh_tags, str):
                stats["tags"] = [t.strip() for t in fresh_tags.split(",") if t.strip()]

    return stats


def _extract_float(data: dict, keys: list[str], default: float) -> float:
    """Try to extract a float value from data using multiple possible keys."""
    for k in keys:
        v = data.get(k)
        if v is not None and not isinstance(v, bool):
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return default


def compute_changes(old: dict, new: dict) -> dict:
    """Compute changes between old and new stats.

    Returns a dict with deltas and change percentages.
    """
    changes = {}
    for key in ["total_score", "realized_profit", "winrate", "total_trades", "token_num", "avg_holding_hours"]:
        old_val = old.get(key, 0.0)
        new_val = new.get(key, 0.0)
        delta = new_val - old_val
        if old_val and old_val != 0:
            pct_change = (delta / abs(old_val)) * 100
        else:
            pct_change = 0.0 if delta == 0 else 100.0
        changes[key] = {
            "old": old_val,
            "new": new_val,
            "delta": round(delta, 2),
            "pct_change": round(pct_change, 2),
        }
    return changes


def evaluate_wallet(wallet: dict, changes: dict, current_stats: dict) -> dict:
    """Evaluate whether a watchlist wallet should be upgraded or downgraded.

    Returns a dict with action and reason.
    """
    score_delta = changes.get("total_score", {}).get("delta", 0.0)
    profit_delta = changes.get("realized_profit", {}).get("delta", 0.0)
    tags = set(current_stats.get("tags", []))
    current_score = current_stats.get("total_score", 0.0)

    # Downgrade: wash_trader tag
    if DOWGRADE_TAGS & tags:
        return {
            "action": "downgrade_to_blacklist",
            "reason": f"检测到有害标签: {', '.join(DOWGRADE_TAGS & tags)}",
            "urgency": "high",
        }

    # Downgrade: realized profit negative (consistent losses)
    current_profit = current_stats.get("realized_profit", 0.0)
    if current_profit < 0:
        return {
            "action": "downgrade_to_blacklist",
            "reason": f"累计利润为负 (${current_profit:.2f})，判定为亏损钱包",
            "urgency": "high",
        }

    # Upgrade: score jump > threshold AND grade improved
    if score_delta >= SCORE_UPGRADE_THRESHOLD:
        return {
            "action": "upgrade_to_whitelist",
            "reason": f"评分提升 {score_delta:.1f} 分 (≥{SCORE_UPGRADE_THRESHOLD})，表现显著改善",
            "urgency": "medium",
        }

    # Upgrade: profit increase > threshold
    if profit_delta >= PROFIT_UPGRADE_THRESHOLD_USD:
        return {
            "action": "upgrade_to_whitelist",
            "reason": f"利润增加 ${profit_delta:.2f} (≥${PROFIT_UPGRADE_THRESHOLD_USD})，盈利能力提升",
            "urgency": "medium",
        }

    return {
        "action": "keep",
        "reason": "无显著变化，继续观察",
        "urgency": "low",
    }


def apply_actions(
    wallets: list[dict],
    evaluations: dict[str, dict],
    current_stats: dict[str, dict],
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Apply upgrade/downgrade actions and return updated lists.

    Returns: (new_watchlist, new_whitelist, new_blacklist, actions_log)
    """
    old_whitelist = load_whitelist()
    old_blacklist = load_blacklist()

    new_watchlist = []
    new_whitelist = list(old_whitelist)
    new_blacklist = list(old_blacklist)
    actions_log = []

    existing_whitelist_addrs = {w["wallet_address"] for w in old_whitelist}
    existing_blacklist_addrs = {w["wallet_address"] for w in old_blacklist}

    for wallet in wallets:
        addr = wallet["wallet_address"]
        eval_result = evaluations.get(addr, {"action": "keep", "reason": "unknown"})
        action = eval_result["action"]

        # Update wallet with fresh stats for the record
        updated_wallet = dict(wallet)
        if addr in current_stats:
            updated_wallet["stats"] = current_stats[addr]
            # Also update top-level fields
            updated_wallet["total_score"] = current_stats[addr].get("total_score", wallet.get("total_score", 0))
            updated_wallet["tags"] = current_stats[addr].get("tags", wallet.get("tags", []))

        if action == "upgrade_to_whitelist":
            if addr not in existing_whitelist_addrs:
                # Mark as promoted
                updated_wallet["decision"] = "copy"
                updated_wallet["grade"] = "C"
                updated_wallet["promoted_at"] = datetime.now(timezone.utc).isoformat()
                updated_wallet["promotion_reason"] = eval_result["reason"]
                new_whitelist.append(updated_wallet)
                existing_whitelist_addrs.add(addr)
                actions_log.append({
                    "wallet_address": addr,
                    "action": "UPGRADE → WHITELIST",
                    "reason": eval_result["reason"],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            # Remove from watchlist (don't add back)
        elif action == "downgrade_to_blacklist":
            if addr not in existing_blacklist_addrs:
                updated_wallet["decision"] = "reject"
                updated_wallet["grade"] = "E"
                updated_wallet["demoted_at"] = datetime.now(timezone.utc).isoformat()
                updated_wallet["demotion_reason"] = eval_result["reason"]
                new_blacklist.append(updated_wallet)
                existing_blacklist_addrs.add(addr)
                actions_log.append({
                    "wallet_address": addr,
                    "action": "DOWNGRADE → BLACKLIST",
                    "reason": eval_result["reason"],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            # Remove from watchlist
        else:
            # Keep in watchlist
            new_watchlist.append(updated_wallet)

    return new_watchlist, new_whitelist, new_blacklist, actions_log


def save_lists(watchlist: list[dict], whitelist: list[dict], blacklist: list[dict]) -> None:
    """Save updated wallet lists to disk."""
    save_json(WATCHLIST_PATH, watchlist)
    save_json(WHITELIST_PATH, whitelist)
    save_json(BLACKLIST_PATH, blacklist)


def _resolve_env_placeholder(data: dict, key: str) -> str | None:
    """Resolve a ${ENV_VAR} placeholder from the environment."""
    value = data.get(key, "")
    if not isinstance(value, str):
        return None
    if value.startswith("${") and value.endswith("}"):
        env_var = value[2:-1]
        resolved = os.environ.get(env_var, "")
        if not resolved:
            print(f"[WARN] Feishu {key} placeholder {value!r} set but "
                  f"environment variable {env_var!r} is empty; skipping push.")
            return None
        return resolved
    return value


def load_feishu_config() -> dict | None:
    """Load Feishu configuration.

    Credentials are read from environment variables when the config file
    contains ${ENV_VAR} placeholders. This prevents secrets from being
    committed to version control.
    """
    data = load_json_safe(FEISHU_CONFIG_PATH)
    if not isinstance(data, dict) or not data.get("enabled"):
        return None

    resolved: dict[str, object] = dict(data)
    for key in ("app_id", "app_secret", "chat_id"):
        resolved_value = _resolve_env_placeholder(data, key)
        if resolved_value is None:
            print(f"[WARN] Feishu {key} is missing or invalid; skipping push.")
            return None
        resolved[key] = resolved_value

    return resolved


def get_feishu_token(app_id: str, app_secret: str) -> str | None:
    """Get Feishu tenant access token."""
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    payload = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("code") == 0:
                return data.get("tenant_access_token")
    except Exception as exc:
        print(f"[WARN] Feishu token fetch failed: {exc}")
    return None


def send_feishu_message(token: str, chat_id: str, content: str) -> bool:
    """Send a text message to a Feishu chat."""
    url = "https://open.feishu.cn/open-apis/im/v1/messages"
    params = urllib.parse.urlencode({"receive_id_type": "chat_id"})
    full_url = f"{url}?{params}"

    payload = json.dumps({
        "receive_id": chat_id,
        "msg_type": "text",
        "content": json.dumps({"text": content}),
    }).encode("utf-8")

    req = urllib.request.Request(
        full_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("code") == 0
    except Exception as exc:
        print(f"[WARN] Feishu message send failed: {exc}")
        return False


def push_to_feishu(report_md: str) -> bool:
    """Push the watchlist report to Feishu via bot API."""
    feishu_cfg = load_feishu_config()
    if not feishu_cfg:
        print("[INFO] Feishu not configured or disabled; skipping push.")
        return False

    app_id = feishu_cfg.get("app_id")
    app_secret = feishu_cfg.get("app_secret")
    chat_id = feishu_cfg.get("chat_id")

    if not all([app_id, app_secret, chat_id]):
        print("[WARN] Feishu config incomplete; skipping push.")
        return False

    token = get_feishu_token(app_id, app_secret)
    if not token:
        print("[WARN] Failed to get Feishu token; skipping push.")
        return False

    # Truncate if too long for Feishu (max 10k chars roughly)
    content = report_md
    if len(content) > 8000:
        content = content[:7900] + "\n\n... [报告已截断]"

    success = send_feishu_message(token, chat_id, content)
    if success:
        print("[INFO] Feishu push successful.")
    else:
        print("[WARN] Feishu push failed.")
    return success


def generate_markdown_report(
    date_str: str,
    wallets: list[dict],
    changes_map: dict[str, dict],
    evaluations: dict[str, dict],
    actions_log: list[dict],
    api_stats: dict[str, Any],
) -> str:
    """Generate a Markdown daily report."""
    lines = []
    lines.append("# 📊 观察名单每日监控报告")
    lines.append("")
    lines.append(f"**日期**: {date_str}")
    lines.append(f"**监控钱包数**: {len(wallets)}")
    lines.append(f"**生成时间**: {datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Section: Summary
    lines.append("## 📈 监控概览")
    lines.append("")
    upgrade_count = sum(1 for a in actions_log if "UPGRADE" in a["action"])
    downgrade_count = sum(1 for a in actions_log if "DOWNGRADE" in a["action"])
    keep_count = len(wallets) - upgrade_count - downgrade_count

    lines.append(f"- 🟢 升级至白名单: **{upgrade_count}**")
    lines.append(f"- 🔴 降级至黑名单: **{downgrade_count}**")
    lines.append(f"- ⚪ 继续观察: **{keep_count}**")
    lines.append("")

    # Section: Per-wallet details
    lines.append("## 🔍 钱包详情")
    lines.append("")

    for wallet in wallets:
        addr = wallet["wallet_address"]
        short_addr = addr[:6] + "..." + addr[-6:]
        changes = changes_map.get(addr, {})
        eval_result = evaluations.get(addr, {})
        current = extract_stats_for_comparison(wallet, api_stats.get(addr))

        # Determine status emoji
        action = eval_result.get("action", "keep")
        if "upgrade" in action:
            emoji = "🟢"
        elif "downgrade" in action:
            emoji = "🔴"
        else:
            emoji = "⚪"

        lines.append(f"### {emoji} {short_addr}")
        lines.append("")

        # Tags
        tags = current.get("tags", [])
        if tags:
            lines.append(f"**标签**: {', '.join(tags)}")

        # Stats table
        lines.append("")
        lines.append("| 指标 | 前值 | 现值 | 变化 | 变化率 |")
        lines.append("|------|------|------|------|--------|")

        for key, label in [
            ("total_score", "综合评分"),
            ("realized_profit", "已实现利润 (USD)"),
            ("winrate", "胜率 (%)"),
            ("total_trades", "交易数 (7d)"),
            ("token_num", "代币数"),
            ("avg_holding_hours", "平均持仓 (h)"),
        ]:
            c = changes.get(key, {})
            old_v = c.get("old", 0)
            new_v = c.get("new", 0)
            delta = c.get("delta", 0)
            pct = c.get("pct_change", 0)

            # Format values
            if key == "realized_profit":
                old_str = f"${old_v:,.2f}"
                new_str = f"${new_v:,.2f}"
                delta_str = f"${delta:+,.2f}"
            elif key in ("total_trades", "token_num"):
                old_str = f"{int(old_v)}"
                new_str = f"{int(new_v)}"
                delta_str = f"{int(delta):+d}"
            else:
                old_str = f"{old_v:.2f}"
                new_str = f"{new_v:.2f}"
                delta_str = f"{delta:+.2f}"

            pct_str = f"{pct:+.1f}%"
            lines.append(f"| {label} | {old_str} | {new_str} | {delta_str} | {pct_str} |")

        lines.append("")

        # Evaluation
        lines.append(f"**评估**: {eval_result.get('reason', '无')}")
        lines.append(f"**建议动作**: `{eval_result.get('action', 'keep')}`")
        lines.append("")
        lines.append("---")
        lines.append("")

    # Section: Actions
    if actions_log:
        lines.append("## 🚨 自动操作记录")
        lines.append("")
        for action in actions_log:
            lines.append(f"- **{action['action']}** | `{action['wallet_address'][:8]}...` | {action['reason']}")
        lines.append("")

    # Section: Rules
    lines.append("## 📋 升级/降级规则")
    lines.append("")
    lines.append("### 升级条件 (满足任一)")
    lines.append(f"1. 综合评分提升 ≥ **{SCORE_UPGRADE_THRESHOLD}** 分")
    lines.append(f"2. 已实现利润增加 ≥ **${PROFIT_UPGRADE_THRESHOLD_USD:,.0f}**")
    lines.append("")
    lines.append("### 降级条件 (满足任一)")
    lines.append("1. 检测到 `wash_trader` 标签")
    lines.append("2. 累计已实现利润为负数")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*本报告由 GMGN Watchlist Monitor 自动生成*")

    return "\n".join(lines)


def generate_json_report(
    date_str: str,
    wallets: list[dict],
    changes_map: dict[str, dict],
    evaluations: dict[str, dict],
    actions_log: list[dict],
    current_stats: dict[str, dict],
) -> dict:
    """Generate the JSON daily report."""
    return {
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "wallets_monitored": len(wallets),
        "wallet_addresses": get_wallet_addresses(wallets),
        "upgrades": [a for a in actions_log if "UPGRADE" in a["action"]],
        "downgrades": [a for a in actions_log if "DOWNGRADE" in a["action"]],
        "per_wallet": {
            w["wallet_address"]: {
                "changes": changes_map.get(w["wallet_address"], {}),
                "evaluation": evaluations.get(w["wallet_address"], {}),
                "current_stats": current_stats.get(w["wallet_address"], {}),
            }
            for w in wallets
        },
        "summary": {
            "upgrade_count": sum(1 for a in actions_log if "UPGRADE" in a["action"]),
            "downgrade_count": sum(1 for a in actions_log if "DOWNGRADE" in a["action"]),
            "keep_count": len(wallets) - len(actions_log),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Watchlist Daily Monitor")
    parser.add_argument(
        "--push-feishu",
        dest="push_feishu",
        action="store_true",
        default=False,
        help="Push report to Feishu after generation",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=False,
        help="Do not save changes to wallet lists",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Watchlist Daily Monitor")
    print("=" * 60)
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    print(f"Date: {date_str}")
    print(f"Dry-run: {args.dry_run}")
    print("-" * 60)

    # 1. Load watchlist
    wallets = load_watchlist()
    if not wallets:
        print("[ERROR] No wallets in watchlist. Exiting.")
        return 1
    print(f"[1] Loaded {len(wallets)} wallets from watchlist")
    for w in wallets:
        print(f"    - {w['wallet_address'][:16]}... (score: {w.get('total_score', 0)})")

    # 2. Load history
    history = load_history()
    print(f"[2] Loaded history: {len(history)} records")

    # 3. Create GMGN client
    config = ConfigManager()
    api_key = config.gmgn_api_key
    if not api_key:
        print("[ERROR] GMGN API key not found. Set GMGN_API_KEY env var.")
        return 1
    client = GmgnApiClient(api_key=api_key)
    print("[3] GMGN API client initialized")

    # 4. Fetch fresh stats
    addresses = get_wallet_addresses(wallets)
    print(f"[4] Fetching fresh stats for {len(addresses)} wallets...")
    api_stats = fetch_wallet_stats(client, addresses)
    print(f"    Received stats for {len(api_stats)} wallets")

    # 5. Compare and evaluate
    print("[5] Evaluating wallets...")
    changes_map: dict[str, dict] = {}
    evaluations: dict[str, dict] = {}
    current_stats: dict[str, dict] = {}

    for wallet in wallets:
        addr = wallet["wallet_address"]

        # Get historical baseline
        old_stats = history.get(addr)
        if old_stats is None:
            # First run: use the wallet's own stats as baseline
            old_stats = extract_stats_for_comparison(wallet, None)
            print(f"    {addr[:8]}...: no history, using wallet record as baseline")

        # Get current stats
        new_stats = extract_stats_for_comparison(wallet, api_stats.get(addr))
        current_stats[addr] = new_stats

        # Compute changes
        changes = compute_changes(old_stats, new_stats)
        changes_map[addr] = changes

        # Evaluate
        evaluation = evaluate_wallet(wallet, changes, new_stats)
        evaluations[addr] = evaluation

        # Print summary
        score_delta = changes.get("total_score", {}).get("delta", 0)
        profit_delta = changes.get("realized_profit", {}).get("delta", 0)
        action = evaluation["action"]
        action_emoji = "🟢" if "upgrade" in action else "🔴" if "downgrade" in action else "⚪"
        print(f"    {action_emoji} {addr[:16]}... score Δ={score_delta:+.1f}, profit Δ=${profit_delta:+.2f} → {action}")

    # 6. Apply actions
    print("[6] Applying actions...")
    new_watchlist, new_whitelist, new_blacklist, actions_log = apply_actions(
        wallets, evaluations, current_stats
    )

    if actions_log:
        for a in actions_log:
            emoji = "🟢" if "UPGRADE" in a["action"] else "🔴"
            print(f"    {emoji} {a['action']}: {a['wallet_address'][:16]}... | {a['reason']}")
    else:
        print("    No actions required.")

    # 7. Save updated lists (unless dry-run)
    if not args.dry_run:
        print("[7] Saving updated wallet lists...")
        save_lists(new_watchlist, new_whitelist, new_blacklist)
        # Update history with current stats for next run
        history.update(current_stats)
        save_history(history)
        print(f"    Watchlist: {len(new_watchlist)} wallets")
        print(f"    Whitelist: {len(new_whitelist)} wallets")
        print(f"    Blacklist: {len(new_blacklist)} wallets")
    else:
        print("[7] Dry-run mode — lists NOT saved.")
        print(f"    Would save: Watchlist={len(new_watchlist)}, Whitelist={len(new_whitelist)}, Blacklist={len(new_blacklist)}")

    # 8. Generate reports
    print("[8] Generating reports...")
    json_report = generate_json_report(
        date_str, wallets, changes_map, evaluations, actions_log, current_stats
    )
    save_json(REPORT_JSON_PATH, json_report)
    print(f"    JSON report: {REPORT_JSON_PATH}")

    md_report = generate_markdown_report(
        date_str, wallets, changes_map, evaluations, actions_log, api_stats
    )
    with open(REPORT_MD_PATH, "w", encoding="utf-8") as f:
        f.write(md_report)
    print(f"    Markdown report: {REPORT_MD_PATH}")

    # 9. Push to Feishu
    if args.push_feishu:
        print("[9] Pushing to Feishu...")
        push_to_feishu(md_report)
    else:
        print("[9] Feishu push skipped (use --push-feishu to enable)")

    print("=" * 60)
    print("Watchlist monitor complete.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
