#!/usr/bin/env python3
"""Candidate wallet scoring and filtering pipeline — v2.

Uses per-wallet GMGN API stats (single-address queries) to build accurate
features for scoring and filtering.

Usage: python3 scripts/score_and_filter_wallets_v2.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from gmgn_monitor.gmgn_api_client import GmgnApiClient
from gmgn_monitor.wallet_scorer import score_wallet, WalletScoringWeights
from gmgn_monitor.wallet_filter import filter_wallet, FilterThresholds

API_KEY = os.getenv("GMGN_API_KEY")
if not API_KEY:
    raise ValueError("GMGN_API_KEY environment variable is required")
CANDIDATE_PATH = Path("data/candidate_wallets_smartmoney.json")
OUTPUT_PATH = Path("data/whitelist_wallets.json")
BLACKLIST_PATH = Path("data/blacklist_wallets.json")
WATCHLIST_PATH = Path("data/watchlist_wallets.json")


def load_candidates() -> list[dict]:
    with open(CANDIDATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_single_wallet_stats(client: GmgnApiClient, address: str) -> dict:
    """Fetch stats for a single wallet address."""
    try:
        return client.get_wallet_stats("sol", [address], period="7d")
    except Exception as e:
        return {"_error": str(e)}


def parse_wallet_stats(stats: dict) -> dict:
    """Parse GMGN API wallet stats into usable metrics."""
    if not stats or "_error" in stats:
        return {}
    
    buy = int(stats.get("buy", 0) or 0)
    sell = int(stats.get("sell", 0) or 0)
    total_trades = buy + sell
    
    pnl = stats.get("pnl_stat", {}) or {}
    winrate = (pnl.get("winrate", 0) or 0) * 100  # 0.3869 -> 38.69%
    token_num = int(pnl.get("token_num", 0) or 0)
    avg_holding_seconds = float(pnl.get("avg_holding_period", 0) or 0)
    avg_holding_hours = avg_holding_seconds / 3600.0
    
    realized_profit = float(stats.get("realized_profit", "0") or "0")
    
    # created_at from common.created_at (unix timestamp)
    common = stats.get("common", {}) or {}
    created_at = int(common.get("created_at", 0) or 0)
    
    # Derive wallet age from created_at
    if created_at > 0:
        now = int(time.time())
        wallet_age_days = max(0, (now - created_at) // 86400)
    else:
        wallet_age_days = 30
    
    return {
        "total_trades": total_trades,
        "buy": buy,
        "sell": sell,
        "winrate": winrate,
        "token_num": token_num,
        "avg_holding_hours": avg_holding_hours,
        "realized_profit": realized_profit,
        "wallet_age_days": wallet_age_days,
        "api_tags": common.get("tags", []),
    }


def build_score_features(wallet: dict, stats: dict) -> dict:
    """Build nested features dict for score_wallet."""
    addr = wallet["address"]
    tags = wallet.get("tags", [])
    volume_usd = wallet.get("volume_usd", 0)
    
    total_trades = stats.get("total_trades", 0)
    winrate = stats.get("winrate", 0)
    avg_holding_hours = stats.get("avg_holding_hours", 0)
    realized_profit = stats.get("realized_profit", 0)
    token_num = stats.get("token_num", 0)
    wallet_age_days = stats.get("wallet_age_days", 30)
    
    # Estimate profit in SOL (~$200/SOL)
    sol_price = 200.0
    total_pnl_sol = realized_profit / sol_price if realized_profit else 0
    profit_30d = total_pnl_sol  # Simplify
    
    # Estimate avg position
    avg_position_usd = volume_usd / max(total_trades, 1) if total_trades else 0
    avg_position_sol = avg_position_usd / sol_price
    
    # Frequency estimates — use REAL trade counts from API stats
    # GMGN wallet_stats period='7d' returns 7-day data, so total_trades ≈ trades_7d
    trades_7d = total_trades if total_trades > 0 else wallet.get("trades", 0)
    trades_30d = total_trades * 4 if total_trades > 0 else wallet.get("trades", 0) * 4
    avg_daily_trades = trades_7d / 7.0 if trades_7d else 0
    
    # P/L ratio estimate
    if winrate > 0 and total_trades > 0:
        pl_ratio = max(0.5, (winrate / 100) * 3.0)
    else:
        pl_ratio = 0.0
    
    # Bot detection
    bot_tags = {"wash_trader", "bot", "sniper"}
    bot_pattern_score = 0
    sniper_detected = False
    if any(t in bot_tags for t in tags):
        bot_pattern_score = 80
    if "sniper" in tags or avg_holding_hours < 0.5:
        bot_pattern_score = max(bot_pattern_score, 50)
        sniper_detected = True
    if total_trades > 100 and avg_holding_hours < 1:
        bot_pattern_score = max(bot_pattern_score, 60)
    if total_trades > 500:
        bot_pattern_score = max(bot_pattern_score, 70)
    
    # MEV / Pump.fun
    mev_usage = 100 if "mev" in tags or "mev_attacker" in tags else 0
    pump_fun_pct = 100 if "pump_fun" in tags or "pump_fun_gambler" in tags else 0
    
    # Risk metrics (estimates)
    max_drawdown = 30.0 if winrate > 40 else 50.0
    sharpe = max(0, (winrate / 100) * 2.0)
    sortino = max(0, (winrate / 100) * 2.5)
    max_consecutive_losses = max(1, int((100 - winrate) / 10))
    
    # Diversification
    diversification = min(1.0, token_num / 100.0) if token_num else 0.1
    
    # first_seen_at
    now = int(time.time())
    first_seen = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - wallet_age_days * 86400)) if wallet_age_days else "2024-01-01T00:00:00Z"
    
    return {
        "wallet_address": addr,
        "chain": "solana",
        "profit_metrics": {
            "win_rate_percent": winrate,
            "profit_loss_ratio": pl_ratio,
            "profit_sol_30d": profit_30d,
            "total_pnl_sol": total_pnl_sol,
            "max_consecutive_losses": max_consecutive_losses,
        },
        "frequency_metrics": {
            "trades_7d": trades_7d,
            "trades_30d": trades_30d,
            "avg_holding_hours": avg_holding_hours,
            "median_holding_hours": avg_holding_hours * 0.8,
            "avg_daily_trades": avg_daily_trades,
        },
        "capital_metrics": {
            "avg_position_sol": avg_position_sol,
        },
        "risk_metrics": {
            "max_drawdown_percent": max_drawdown,
            "sharpe_ratio": sharpe,
            "sortino_ratio": sortino,
        },
        "behavioral_metrics": {
            "bot_pattern_score": bot_pattern_score,
            "sniper_detected": sniper_detected,
            "mev_usage_percent": mev_usage,
        },
        "token_preference": {
            "pump_fun_interaction_percent": pump_fun_pct,
        },
        "total_transactions": total_trades,
        "first_seen_at": first_seen,
    }


def build_filter_features(features: dict, stats: dict) -> dict:
    """Build flat features for filter_wallet."""
    return {
        "wallet_address": features["wallet_address"],
        "win_rate_percent": features["profit_metrics"]["win_rate_percent"],
        "total_trades": features["total_transactions"],
        "trades_7d": features["frequency_metrics"]["trades_7d"],
        "trades_30d": features["frequency_metrics"]["trades_30d"],
        "avg_holding_hours": features["frequency_metrics"]["avg_holding_hours"],
        "total_profit_usd": stats.get("realized_profit", 0),
        "wallet_age_days": stats.get("wallet_age_days", 30),
        "diversification_index": stats.get("token_num", 0) / 100.0,
        "is_mev_attacker": features["behavioral_metrics"]["mev_usage_percent"] > 50,
        "is_dev_associated": False,
        "single_token_concentration_percent": 0,
        "self_transfer_ratio_percent": 0,
        "inactive_days": 0,
        "volatility_30d": 0.3,
        "turbo_slippage_usage_percent": 0,
        "mev_usage_percent": features["behavioral_metrics"]["mev_usage_percent"],
        "pump_fun_interaction_percent": features["token_preference"]["pump_fun_interaction_percent"],
        "large_gambler_ratio_percent": 0,
        "stop_loss_trigger_rate_percent": 50,
    }


def main():
    print("=" * 60)
    print("GMGN 候选钱包评分与过滤流程 v2")
    print("=" * 60)
    
    candidates = load_candidates()
    print(f"\n📋 加载候选钱包: {len(candidates)} 个")
    
    client = GmgnApiClient(API_KEY)
    
    # Fetch stats for each wallet (single-address queries)
    print(f"\n🌐 从 GMGN API 获取钱包 stats (逐个查询)...")
    stats_map = {}
    for i, wallet in enumerate(candidates, 1):
        addr = wallet["address"]
        print(f"   [{i}/{len(candidates)}] {addr[:20]}... ", end="", flush=True)
        stats = fetch_single_wallet_stats(client, addr)
        if "_error" in stats:
            print(f"✗ {stats['_error']}")
            stats_map[addr] = {}
        else:
            parsed = parse_wallet_stats(stats)
            stats_map[addr] = parsed
            print(f"✓ trades={parsed.get('total_trades', 0)}, winrate={parsed.get('winrate', 0):.1f}%, profit=${parsed.get('realized_profit', 0):.2f}")
    
    print(f"\n📊 开始评分与过滤...")
    print(f"{'='*60}")
    
    whitelist = []
    blacklist = []
    watchlist = []
    
    for wallet in candidates:
        addr = wallet["address"]
        tags = wallet.get("tags", [])
        stats = stats_map.get(addr, {})
        
        # Hard reject: wash_trader
        if "wash_trader" in tags:
            result = {
                "wallet_address": addr,
                "total_score": 0.0,
                "grade": "E",
                "decision": "reject",
                "reasons": ["wash_trader 标签 (一票否决)"],
                "tags": tags,
            }
            blacklist.append(result)
            print(f"\n🚫 {addr[:20]}... | 评分: 0 | 决策: reject | 原因: wash_trader")
            continue
        
        # Build features
        score_features = build_score_features(wallet, stats)
        filter_features = build_filter_features(score_features, stats)
        
        # Score with Meme-coin friendly weights and thresholds
        meme_score_weights = WalletScoringWeights(
            min_trades_for_scoring=5,
            max_trades_7d=2000,
            min_win_rate_hard=20.0,
            min_avg_holding_hours=0.05,
            max_robot_score=80.0,
            bot_pattern_penalty_threshold=30.0,
            win_rate_penalty_threshold=35.0,
            # Lower thresholds for meme coin context
            copy_threshold=65.0,   # was 80
            watch_threshold=50.0,  # was 70
            observe_threshold=30.0,  # was 40
        )
        meme_filter_thresholds = FilterThresholds(
            min_data_trades=5,
            min_win_rate_percent=20.0,
            min_avg_holding_hours=0.05,
            pass_score=70,
            watch_score=50,
        )
        score_result = score_wallet(score_features, weights=meme_score_weights)
        filter_result = filter_wallet(filter_features, thresholds=meme_filter_thresholds)
        
        combined = {
            "wallet_address": addr,
            "total_score": score_result["total_score"],
            "grade": score_result["grade"],
            "decision": score_result["decision"],
            "score_reasons": score_result["reasons"],
            "filter_decision": filter_result["decision"],
            "filter_score": filter_result["score"],
            "filter_reasons": filter_result["reasons"],
            "hard_rejected": filter_result["hard_rejected"],
            "robot_score": filter_result["robot_score"],
            "tags": tags,
            "volume_usd": wallet.get("volume_usd", 0),
            "trades_snapshot": wallet.get("trades", 0),
            "stats": {
                "total_trades": stats.get("total_trades", 0),
                "realized_profit": stats.get("realized_profit", 0),
                "winrate": stats.get("winrate", 0),
                "token_num": stats.get("token_num", 0),
                "avg_holding_hours": stats.get("avg_holding_hours", 0),
                "wallet_age_days": stats.get("wallet_age_days", 0),
            },
            "dimension_scores": score_result["dimension_scores"],
        }
        
        # Classification: strict whitelist based on score + filter
        # Whitelist = score >= 50 (watch+) AND not hard rejected AND profitable
        # Watchlist = score 30-50 AND not hard rejected
        # Blacklist = everything else
        score_ok = score_result["total_score"] >= 50
        not_hard_rejected = not filter_result["hard_rejected"]
        is_profitable = stats.get("realized_profit", 0) > 0
        
        if score_ok and not_hard_rejected and is_profitable:
            whitelist.append(combined)
        elif score_result["total_score"] >= 30 and not_hard_rejected:
            watchlist.append(combined)
        else:
            blacklist.append(combined)
        
        emoji = "✅" if combined in whitelist else ("👁" if combined in watchlist else "❌")
        print(f"\n{emoji} {addr[:20]}...")
        print(f"   评分: {combined['total_score']:.1f} | 等级: {combined['grade']} | 决策: {combined['decision']}")
        print(f"   真实交易: {combined['stats']['total_trades']} | 胜率: {combined['stats']['winrate']:.1f}% | 持仓: {combined['stats']['avg_holding_hours']:.1f}h")
        print(f"   标签: {', '.join(tags) if tags else '无'}")
        if combined['score_reasons']:
            print(f"   原因: {combined['score_reasons'][0]}")
    
    # Sort by score descending
    whitelist.sort(key=lambda x: x["total_score"], reverse=True)
    watchlist.sort(key=lambda x: x["total_score"], reverse=True)
    blacklist.sort(key=lambda x: x["total_score"], reverse=True)
    
    # Summary
    print(f"\n{'='*60}")
    print(f"📊 评分结果汇总")
    print(f"{'='*60}")
    print(f"✅ 白名单 (copy/pass): {len(whitelist)} 个")
    print(f"👁 观察名单 (watch): {len(watchlist)} 个")
    print(f"🚫 黑名单 (reject): {len(blacklist)} 个")
    
    # Save
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(whitelist, f, indent=2, ensure_ascii=False)
    with open(WATCHLIST_PATH, "w", encoding="utf-8") as f:
        json.dump(watchlist, f, indent=2, ensure_ascii=False)
    with open(BLACKLIST_PATH, "w", encoding="utf-8") as f:
        json.dump(blacklist, f, indent=2, ensure_ascii=False)
    
    print(f"\n💾 白名单: {OUTPUT_PATH}")
    print(f"💾 观察名单: {WATCHLIST_PATH}")
    print(f"💾 黑名单: {BLACKLIST_PATH}")
    
    # Top whitelist
    if whitelist:
        print(f"\n{'='*60}")
        print(f"🏆 TOP 白名单钱包")
        print(f"{'='*60}")
        for i, w in enumerate(whitelist[:10], 1):
            print(f"{i}. {w['wallet_address']}")
            print(f"   评分: {w['total_score']:.1f} | 等级: {w['grade']}")
            print(f"   交易: {w['stats']['total_trades']} | 胜率: {w['stats']['winrate']:.1f}% | 利润: ${w['stats']['realized_profit']:.2f}")
    
    print(f"\n{'='*60}")
    print("✅ 评分与过滤流程完成")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
