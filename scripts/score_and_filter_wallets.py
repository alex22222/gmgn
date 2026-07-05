#!/usr/bin/env python3
"""Candidate wallet scoring and filtering pipeline.

Usage: python3 scripts/score_and_filter_wallets.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from gmgn_monitor.gmgn_api_client import GmgnApiClient
from gmgn_monitor.wallet_scorer import score_wallet, WalletScoringWeights
from gmgn_monitor.wallet_filter import filter_wallet, FilterThresholds
from gmgn_monitor.wallet_robot_detector import detect_robot, WalletFeatures

API_KEY = os.getenv("GMGN_API_KEY")
if not API_KEY:
    raise ValueError("GMGN_API_KEY environment variable is required")
CANDIDATE_PATH = Path("data/candidate_wallets_smartmoney.json")
OUTPUT_PATH = Path("data/whitelist_wallets.json")
BLACKLIST_PATH = Path("data/blacklist_wallets.json")


def load_candidates() -> list[dict]:
    with open(CANDIDATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_wallet_stats(client: GmgnApiClient, addresses: list[str]) -> dict:
    """Fetch wallet stats for all addresses in one batch."""
    return client.get_wallet_stats("sol", addresses, period="7d")


def map_api_to_score_features(wallet: dict, stats: dict) -> dict:
    """Map GMGN API wallet stats to score_wallet features."""
    addr = wallet["address"]
    tags = wallet.get("tags", [])
    
    # Extract stats
    realized_profit = stats.get("realized_profit", 0)
    winrate = stats.get("winrate", 0) * 100  # Convert to percent
    buy = stats.get("buy", 0)
    sell = stats.get("sell", 0)
    total_trades = buy + sell
    token_num = stats.get("pnl_stat", {}).get("token_num", 0)
    avg_holding_seconds = stats.get("avg_holding_period", 0)
    avg_holding_hours = avg_holding_seconds / 3600.0
    
    # Estimate profit in SOL (approx $200/SOL)
    sol_price = 200.0
    total_pnl_sol = realized_profit / sol_price if realized_profit else 0
    profit_30d = total_pnl_sol  # Simplify: 7d ≈ recent
    
    # Estimate avg position size (volume / trades / SOL_price)
    volume_usd = wallet.get("volume_usd", 0)
    avg_position_usd = volume_usd / max(total_trades, 1) if total_trades else 0
    avg_position_sol = avg_position_usd / sol_price
    
    # Estimate trades per period
    trades_7d = wallet.get("trades", 0)  # From recent 100 tx snapshot
    trades_30d = total_trades  # Total from stats
    avg_daily_trades = trades_7d / 7.0 if trades_7d else 0
    
    # Estimate P/L ratio (simplified)
    if winrate > 0 and total_trades > 0:
        pl_ratio = max(0.5, (winrate / 100) * 3.0)
    else:
        pl_ratio = 0.0
    
    # Bot detection heuristic from tags
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
    
    # MEV detection
    mev_usage = 0
    if "mev" in tags or "mev_attacker" in tags:
        mev_usage = 100
    
    # Pump.fun detection
    pump_fun_pct = 0
    if "pump_fun" in tags or "pump_fun_gambler" in tags:
        pump_fun_pct = 100
    
    # Risk metrics (estimates from available data)
    max_drawdown = 30.0 if winrate > 40 else 50.0
    sharpe = max(0, (winrate / 100) * 2.0)
    sortino = max(0, (winrate / 100) * 2.5)
    
    # Max consecutive losses (estimate)
    max_consecutive_losses = max(1, int((100 - winrate) / 10))
    
    # Diversification
    diversification = min(1.0, token_num / 100.0) if token_num else 0.1
    
    # Account age (from tags)
    first_seen = "2024-01-01T00:00:00Z"  # Default
    if "fresh_wallet" in tags:
        first_seen = "2025-05-01T00:00:00Z"
    
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
        # Also include flat version for filter_wallet
        "win_rate_percent": winrate,
        "total_trades": total_trades,
        "trades_30d": trades_30d,
        "avg_holding_hours": avg_holding_hours,
        "total_profit_usd": realized_profit,
        "wallet_age_days": 30,  # Simplified
        "diversification_index": diversification,
    }


def map_to_filter_features(features: dict) -> WalletFeatures:
    """Map to flat WalletFeatures for filter_wallet."""
    return {
        "wallet_address": features["wallet_address"],
        "win_rate_percent": features["profit_metrics"]["win_rate_percent"],
        "total_trades": features["total_transactions"],
        "trades_7d": features["frequency_metrics"]["trades_7d"],
        "trades_30d": features["frequency_metrics"]["trades_30d"],
        "avg_holding_hours": features["frequency_metrics"]["avg_holding_hours"],
        "total_profit_usd": features["total_profit_usd"],
        "wallet_age_days": features["wallet_age_days"],
        "diversification_index": features["diversification_index"],
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
    print("GMGN 候选钱包评分与过滤流程")
    print("=" * 60)
    
    # 1. Load candidates
    candidates = load_candidates()
    print(f"\n📋 加载候选钱包: {len(candidates)} 个")
    
    # 2. Fetch wallet stats from GMGN API (batch)
    print(f"\n🌐 从 GMGN API 获取钱包 stats...")
    addresses = [w["address"] for w in candidates]
    client = GmgnApiClient(API_KEY)
    
    try:
        stats_data = fetch_wallet_stats(client, addresses)
        print(f"   ✓ API 返回数据")
    except Exception as e:
        print(f"   ✗ API 调用失败: {e}")
        # Fallback: use empty stats for all
        stats_data = {}
    
    # GMGN API returns dict of wallet_address -> stats
    if not isinstance(stats_data, dict):
        stats_data = {}
    
    # 3. Score and filter each wallet
    whitelist = []
    blacklist = []
    watchlist = []
    
    print(f"\n📊 开始评分与过滤...")
    print(f"{'='*60}")
    
    for wallet in candidates:
        addr = wallet["address"]
        tags = wallet.get("tags", [])
        
        # Get stats for this wallet
        wallet_stats = stats_data.get(addr, {})
        
        # Build features
        features = map_api_to_score_features(wallet, wallet_stats)
        
        # Step 1: Tag-based hard reject (before scoring)
        if "wash_trader" in tags:
            result = {
                "wallet_address": addr,
                "total_score": 0.0,
                "grade": "E",
                "decision": "reject",
                "reasons": ["wash_trader tag (一票否决)"],
                "tags": tags,
                "volume_usd": wallet.get("volume_usd", 0),
            }
            blacklist.append(result)
            print(f"\n🚫 {addr[:20]}... | 评分: 0 | 等级: E | 决策: reject")
            print(f"   原因: wash_trader 标签 (一票否决)")
            continue
        
        # Step 2: Score wallet
        score_result = score_wallet(features)
        
        # Step 3: Filter wallet
        filter_features = map_to_filter_features(features)
        filter_result = filter_wallet(filter_features)
        
        # Combine results
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
            "trades": wallet.get("trades", 0),
            "stats": {
                "realized_profit": wallet_stats.get("realized_profit", 0),
                "winrate": wallet_stats.get("winrate", 0) * 100,
                "total_trades": wallet_stats.get("buy", 0) + wallet_stats.get("sell", 0),
                "token_num": wallet_stats.get("pnl_stat", {}).get("token_num", 0),
                "avg_holding_hours": features["frequency_metrics"]["avg_holding_hours"],
            },
            "dimension_scores": score_result["dimension_scores"],
        }
        
        # Determine final classification
        if score_result["decision"] == "copy" or filter_result["decision"] == "pass":
            whitelist.append(combined)
        elif score_result["decision"] == "watch" or filter_result["decision"] == "watch":
            watchlist.append(combined)
        else:
            blacklist.append(combined)
        
        print(f"\n{'✅' if combined['decision'] in ('copy', 'watch') else '❌'} {addr[:20]}...")
        print(f"   评分: {combined['total_score']} | 等级: {combined['grade']} | 决策: {combined['decision']}")
        print(f"   标签: {', '.join(tags) if tags else '无'}")
        print(f"   原因: {combined['score_reasons'][0] if combined['score_reasons'] else 'N/A'}")
    
    # 4. Sort whitelist by score descending
    whitelist.sort(key=lambda x: x["total_score"], reverse=True)
    watchlist.sort(key=lambda x: x["total_score"], reverse=True)
    blacklist.sort(key=lambda x: x["total_score"], reverse=True)
    
    # 5. Save results
    print(f"\n{'='*60}")
    print(f"📊 评分结果汇总")
    print(f"{'='*60}")
    print(f"✅ 白名单 (copy/pass): {len(whitelist)} 个")
    print(f"👁 观察名单 (watch): {len(watchlist)} 个")
    print(f"🚫 黑名单 (reject): {len(blacklist)} 个")
    
    # Save whitelist
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(whitelist, f, indent=2, ensure_ascii=False)
    print(f"\n💾 白名单已保存: {OUTPUT_PATH}")
    
    # Save blacklist
    with open(BLACKLIST_PATH, "w", encoding="utf-8") as f:
        json.dump(blacklist, f, indent=2, ensure_ascii=False)
    print(f"💾 黑名单已保存: {BLACKLIST_PATH}")
    
    # 6. Print top whitelist wallets
    if whitelist:
        print(f"\n{'='*60}")
        print(f"🏆 TOP 白名单钱包")
        print(f"{'='*60}")
        for i, w in enumerate(whitelist[:10], 1):
            print(f"{i}. {w['wallet_address']}")
            print(f"   评分: {w['total_score']} | 等级: {w['grade']}")
            print(f"   交易量: ${w['volume_usd']:.2f} | 标签: {', '.join(w['tags'])}")
            if w['stats']['realized_profit']:
                print(f"   已实现利润: ${w['stats']['realized_profit']:.2f}")
    
    print(f"\n{'='*60}")
    print("✅ 评分与过滤流程完成")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
