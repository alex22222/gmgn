#!/usr/bin/env python3
"""
GMGN 白名单钱包模拟跟单测试

用法：
    python3 scripts/simulate_copy_trading.py --capital 10 --duration-hours 24 --output data/simulation_report.json
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def load_wallets(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def simulate_wallet_trades(
    wallet: dict,
    capital_sol: float,
    position_size_sol: float,
    max_positions: int,
    duration_hours: int,
    rng: random.Random,
) -> list[dict]:
    """Simulate copy-trading a single whitelist wallet for N hours."""
    stats = wallet.get("stats", {})
    winrate = float(stats.get("winrate", 50)) / 100.0
    total_trades_7d = int(stats.get("total_trades", 0))
    realized_profit = float(stats.get("realized_profit", 0))
    avg_holding_hours = float(stats.get("avg_holding_hours", 2))
    wallet_age_days = float(stats.get("wallet_age_days", 30))

    # Derive daily trade frequency from 7-day total
    daily_trades = max(1, total_trades_7d / 7)
    # Scale to requested duration
    expected_trades = max(1, round(daily_trades * (duration_hours / 24)))

    # Estimate avg profit per trade from realized_profit / total_trades
    total_trades_all = max(1, total_trades_7d)
    avg_profit_per_trade = realized_profit / total_trades_all

    # Apply a realistic spread: some wins are big, some losses are moderate
    # Meme coin pattern: winners 2-10x, losers -50% to -100%
    trades: list[dict] = []
    open_positions: list[dict] = []
    closed_trades: list[dict] = []

    now = datetime.now(timezone.utc)
    for i in range(expected_trades):
        trade_time = now + timedelta(hours=(duration_hours / max(1, expected_trades)) * i)
        is_win = rng.random() < winrate

        if is_win:
            # Win: 1.5x to 8x return on position
            multiplier = rng.uniform(1.5, 8.0)
            profit = position_size_sol * (multiplier - 1.0)
            exit_reason = "take_profit"
        else:
            # Loss: -50% to -100% of position
            loss_pct = rng.uniform(0.5, 1.0)
            profit = -position_size_sol * loss_pct
            exit_reason = "stop_loss"

        trade = {
            "wallet_address": wallet.get("wallet_address", ""),
            "wallet_score": wallet.get("total_score", 0),
            "wallet_grade": wallet.get("grade", ""),
            "trade_id": f"{wallet.get('wallet_address', '')[:6]}_{i}",
            "entry_time": trade_time.isoformat(),
            "exit_time": (trade_time + timedelta(hours=avg_holding_hours * rng.uniform(0.3, 1.5))).isoformat(),
            "position_size_sol": position_size_sol,
            "profit_sol": round(profit, 6),
            "profit_usd": round(profit * 150, 2),  # ~150 USD per SOL
            "is_win": is_win,
            "exit_reason": exit_reason,
            "token_symbol": f"SIM{i}",
            "token_address": f"SimToken{i}1111111111111111111111111111111111",
        }
        trades.append(trade)

    return trades


def run_simulation(
    whitelist_path: Path,
    capital_sol: float,
    position_size_sol: float,
    max_positions: int,
    duration_hours: int,
    seed: int | None = None,
) -> dict[str, Any]:
    """Run a full 1-day copy-trading simulation against all whitelist wallets."""
    wallets = load_wallets(whitelist_path)
    if not wallets:
        raise ValueError("No whitelist wallets found")

    rng = random.Random(seed)
    all_trades: list[dict] = []

    for wallet in wallets:
        trades = simulate_wallet_trades(
            wallet=wallet,
            capital_sol=capital_sol,
            position_size_sol=position_size_sol,
            max_positions=max_positions,
            duration_hours=duration_hours,
            rng=rng,
        )
        all_trades.extend(trades)

    # Sort by entry time
    all_trades.sort(key=lambda t: t["entry_time"])

    # Calculate summary
    total_trades = len(all_trades)
    wins = sum(1 for t in all_trades if t["is_win"])
    losses = total_trades - wins
    total_profit_sol = sum(t["profit_sol"] for t in all_trades)
    total_profit_usd = sum(t["profit_usd"] for t in all_trades)
    win_rate = wins / total_trades if total_trades else 0
    avg_profit = total_profit_sol / total_trades if total_trades else 0

    # Max drawdown simulation
    running_pnl = 0.0
    max_drawdown = 0.0
    peak = 0.0
    for t in all_trades:
        running_pnl += t["profit_sol"]
        if running_pnl > peak:
            peak = running_pnl
        drawdown = peak - running_pnl
        if drawdown > max_drawdown:
            max_drawdown = drawdown

    return {
        "meta": {
            "simulated_at": datetime.now(timezone.utc).isoformat(),
            "start_time": datetime.now(timezone.utc).isoformat(),
            "end_time": (datetime.now(timezone.utc) + timedelta(hours=duration_hours)).isoformat(),
            "capital_sol": capital_sol,
            "position_size_sol": position_size_sol,
            "max_positions": max_positions,
            "duration_hours": duration_hours,
            "seed": seed,
        },
        "wallets": [
            {
                "address": w.get("wallet_address", ""),
                "score": w.get("total_score", 0),
                "grade": w.get("grade", ""),
                "winrate": w.get("stats", {}).get("winrate", 0),
            }
            for w in wallets
        ],
        "summary": {
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate * 100, 2),
            "total_profit_sol": round(total_profit_sol, 6),
            "total_profit_usd": round(total_profit_usd, 2),
            "avg_profit_per_trade_sol": round(avg_profit, 6),
            "max_drawdown_sol": round(max_drawdown, 6),
            "final_capital_sol": round(capital_sol + total_profit_sol, 6),
            "roi_percent": round((total_profit_sol / capital_sol) * 100, 2) if capital_sol else 0,
        },
        "trades": all_trades,
    }


def render_report(result: dict[str, Any]) -> str:
    """Render a human-readable markdown report."""
    meta = result["meta"]
    summary = result["summary"]
    wallets = result["wallets"]
    trades = result["trades"]

    lines = []
    lines.append("# GMGN 白名单钱包模拟跟单测试报告")
    lines.append("")
    lines.append(f"- 模拟时间：{meta['simulated_at']}")
    lines.append(f"- 测试时段：{meta['start_time']} → {meta['end_time']}")
    lines.append(f"- 起始资金：{meta['capital_sol']} SOL")
    lines.append(f"- 单笔跟单：{meta['position_size_sol']} SOL")
    lines.append(f"- 最大持仓：{meta['max_positions']} 个")
    lines.append("")
    lines.append("## 跟单钱包列表")
    lines.append("")
    lines.append("| 钱包地址 | 评分 | 等级 | 原始胜率 |")
    lines.append("|----------|------|------|----------|")
    for w in wallets:
        addr = w["address"]
        short = f"{addr[:6]}...{addr[-4:]}" if len(addr) > 20 else addr
        lines.append(f"| {short} | {w['score']:.1f} | {w['grade']} | {w['winrate']:.1f}% |")
    lines.append("")
    lines.append("## 测试结果汇总")
    lines.append("")
    lines.append(f"- **总交易笔数**：{summary['total_trades']}")
    lines.append(f"- **盈利笔数**：{summary['wins']} ✅")
    lines.append(f"- **亏损笔数**：{summary['losses']} ❌")
    lines.append(f"- **模拟胜率**：{summary['win_rate']:.1f}%")
    lines.append(f"- **总盈亏 SOL**：{summary['total_profit_sol']:+.6f}")
    lines.append(f"- **总盈亏 USD**：${summary['total_profit_usd']:+.2f}")
    lines.append(f"- **平均单笔盈亏**：{summary['avg_profit_per_trade_sol']:+.6f} SOL")
    lines.append(f"- **最大回撤 SOL**：{summary['max_drawdown_sol']:.6f}")
    lines.append(f"- **最终资金**：{summary['final_capital_sol']:.6f} SOL")
    lines.append(f"- **ROI**：{summary['roi_percent']:+.2f}%")
    lines.append("")
    lines.append("## 交易明细")
    lines.append("")
    lines.append("| # | 钱包 | 代币 | 方向 | 盈亏(SOL) | 盈亏(USD) | 结果 | 退出原因 |")
    lines.append("|---|------|------|------|-----------|-----------|------|----------|")
    for i, t in enumerate(trades[:50], 1):  # Show first 50
        w_short = f"{t['wallet_address'][:6]}...{t['wallet_address'][-4:]}"
        result_emoji = "✅" if t["is_win"] else "❌"
        lines.append(
            f"| {i} | {w_short} | {t['token_symbol']} | "
            f"{'买入' if t['is_win'] else '买入'} | "
            f"{t['profit_sol']:+.6f} | {t['profit_usd']:+.2f} | "
            f"{result_emoji} | {t['exit_reason']} |"
        )
    if len(trades) > 50:
        lines.append(f"| ... | 共 {len(trades)} 笔交易，仅展示前 50 笔 | | | | | | |")
    lines.append("")
    lines.append("---")
    lines.append("*注：本报告为模拟结果，不代表真实交易表现。")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="GMGN 白名单钱包模拟跟单测试")
    parser.add_argument("--whitelist", type=Path, default=Path("data/whitelist_wallets.json"))
    parser.add_argument("--capital", type=float, default=10.0, help="模拟起始资金 (SOL)")
    parser.add_argument("--position-size", type=float, default=0.005, help="单笔跟单金额 (SOL)")
    parser.add_argument("--max-positions", type=int, default=3, help="最大同时持仓数")
    parser.add_argument("--duration-hours", type=int, default=24, help="测试时长（小时）")
    parser.add_argument("--output", type=Path, default=Path("data/simulation_report.json"))
    parser.add_argument("--report", type=Path, default=Path("data/simulation_report.md"))
    parser.add_argument("--seed", type=int, default=None, help="随机种子（可复现）")
    args = parser.parse_args()

    result = run_simulation(
        whitelist_path=args.whitelist,
        capital_sol=args.capital,
        position_size_sol=args.position_size,
        max_positions=args.max_positions,
        duration_hours=args.duration_hours,
        seed=args.seed,
    )

    # Save JSON
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"JSON 报告已保存：{args.output}")

    # Save Markdown
    report = render_report(result)
    with open(args.report, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"Markdown 报告已保存：{args.report}")

    # Print summary
    s = result["summary"]
    print(f"\n{'='*50}")
    print("模拟跟单测试完成")
    print(f"{'='*50}")
    print(f"总交易: {s['total_trades']} 笔 | 盈利: {s['wins']} | 亏损: {s['losses']}")
    print(f"胜率: {s['win_rate']:.1f}%")
    print(f"总盈亏: {s['total_profit_sol']:+.6f} SOL (${s['total_profit_usd']:+.2f})")
    print(f"起始资金: {args.capital} SOL → 最终资金: {s['final_capital_sol']:.6f} SOL")
    print(f"ROI: {s['roi_percent']:+.2f}%")
    print(f"最大回撤: {s['max_drawdown_sol']:.6f} SOL")
    print(f"{'='*50}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
