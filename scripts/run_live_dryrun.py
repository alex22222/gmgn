#!/usr/bin/env python3
"""Run a live-signal dry-run using the EnhancedDataPipeline with multi-source
signal merging and source-quality scoring.

Usage:
    python3 scripts/run_live_dryrun.py [--dry-run]

The script always prevents real trades regardless of the --dry-run flag.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gmgn_monitor.config_manager import ConfigManager
from gmgn_monitor.dry_run_executor import DryRunExecutor
from gmgn_monitor.enhanced_data_pipeline import EnhancedDataPipeline
from gmgn_monitor.risk_manager import RiskLimits


def compute_source_quality_score(signal: dict) -> int:
    """Compute a quality score based on the number of confirming sources.

    Scoring:
        1 source = 50%
        2 sources = 70%
        3 sources = 85%
        4 sources = 95%
    """
    count = signal.get("source_confidence", 1)
    return {1: 50, 2: 70, 3: 85, 4: 95}.get(count, 50)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Live-signal dry-run using EnhancedDataPipeline"
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="Prevent real trades (default: True). Always enforced.",
    )
    parser.add_argument(
        "--chain",
        type=str,
        default="sol",
        help="Chain to query (default: sol)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Number of smart-money wallets to fetch (default: 50)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/live_dryrun_results.json",
        help="Output JSON path (default: data/live_dryrun_results.json)",
    )
    parser.add_argument(
        "--sources",
        type=str,
        default="gmgn,birdeye,helius,dexscreener",
        help="Comma-separated list of sources (default: gmgn,birdeye,helius,dexscreener)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Live-Signal Dry-Run (Enhanced Data Pipeline)")
    print("=" * 60)
    print(f"Chain: {args.chain}")
    print(f"Dry-run mode: {args.dry_run} (real trades are ALWAYS prevented)")
    print("-" * 60)

    # 1. Load API key from ConfigManager
    config = ConfigManager()
    api_key = config.gmgn_api_key
    if not api_key:
        print("WARNING: GMGN API key not found. GMGN source will be unavailable.")
    else:
        print("[1] API key loaded from ConfigManager")

    # 2. Create EnhancedDataPipeline with all sources
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    pipeline = EnhancedDataPipeline(
        sources=sources,
        gmgn_api_key=api_key,
    )
    print(f"[2] EnhancedDataPipeline created with sources: {sources}")

    # 3. Fetch smart-money wallet list from GMGN and then signals from all sources
    wallet_scores: dict[str, float] = {}
    all_signals: list[dict] = []

    # Try to get smart-money wallets from GMGN first
    gmgn_client = pipeline._gmgn
    if gmgn_client is not None:
        print("[3] Fetching smart-money wallet list from GMGN...")
        try:
            from gmgn_monitor.gmgn_data_mapper import map_smartmoney_list_to_wallet_addresses
            raw = gmgn_client.get_smartmoney(chain=args.chain, limit=args.limit)
            wallets = map_smartmoney_list_to_wallet_addresses(raw)
            if not isinstance(wallets, list):
                wallets = []
            print(f"    Found {len(wallets)} smart-money wallets")
        except Exception as exc:
            print(f"    ERROR fetching smart-money list: {exc}")
            wallets = []
    else:
        wallets = []
        print("[3] GMGN unavailable; no smart-money wallet list fetched")

    # 4. Fetch wallet signals from all sources for each wallet
    if wallets:
        print(f"[4] Fetching wallet signals from all sources for {len(wallets)} wallets...")
        for idx, wallet in enumerate(wallets, 1):
            try:
                signals = pipeline.fetch_wallet_signals(wallet, chain=args.chain)
                all_signals.extend(signals)
            except Exception as exc:
                print(f"    Wallet {wallet} failed: {exc}")
            if idx % 10 == 0:
                print(f"    Processed {idx}/{len(wallets)} wallets...")
    else:
        print("[4] No wallets to fetch; skipping wallet signal fetch")

    # Also try trending signals from GMGN
    trending_signals: list[dict] = []
    if gmgn_client is not None:
        print("[5] Fetching trending token signals from GMGN...")
        try:
            raw = gmgn_client.get_trending_swaps(chain=args.chain, interval="1h")
            tokens = raw.get("tokens") or raw.get("data") or []
            if isinstance(tokens, dict):
                tokens = tokens.get("tokens") or tokens.get("data") or []
            if isinstance(tokens, list):
                for token_entry in tokens[:10]:
                    if not isinstance(token_entry, dict):
                        continue
                    token_address = str(
                        token_entry.get("token_address")
                        or token_entry.get("address")
                        or ""
                    )
                    if not token_address:
                        continue
                    # Create a synthetic signal for each trending token
                    trending_signals.append({
                        "wallet_address": "trending",
                        "token_address": token_address,
                        "action": "buy",
                        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                        "price_usd": float(token_entry.get("price", 0.0)),
                        "amount_sol": 0.5,
                        "tx_hash": f"trending-{token_address}",
                        "sources_used": ["gmgn"],
                        "source_confidence": 1,
                        "confidence": 0.6,
                    })
        except Exception as exc:
            print(f"    Trending fetch failed: {exc}")
    print(f"    Fetched {len(trending_signals)} trending signals")

    all_signals.extend(trending_signals)
    print(f"    Total raw signals: {len(all_signals)}")

    # 5. Compute source_quality_score and filter
    print("[6] Computing source quality scores and filtering...")
    filtered_signals: list[dict] = []
    for sig in all_signals:
        score = compute_source_quality_score(sig)
        sig["source_quality_score"] = score
        if score >= 0.70:
            filtered_signals.append(sig)

    print(f"    Signals >= 70% quality: {len(filtered_signals)} / {len(all_signals)}")

    # 6. Convert to TradeSignals
    trade_signals = pipeline.to_trade_signals(filtered_signals, wallet_scores)
    print(f"[7] Converted to {len(trade_signals)} TradeSignals")

    # 7. Create DryRunExecutor
    risk_limits = RiskLimits(
        daily_loss_limit_percent=5.0,
        max_single_position_percent=20.0,
        max_total_positions=5,
        default_stop_loss_percent=-65.0,
    )
    executor = DryRunExecutor(
        initial_balance_sol=10.0,
        risk_limits=risk_limits,
        wallet_scores=wallet_scores,
    )
    print("[8] DryRunExecutor created with 10.0 SOL initial balance")

    # 8. Run simulation
    result = executor.run_simulation(trade_signals)
    print("[9] Simulation complete:")
    print(f"    Orders created: {result['orders_created']}")
    print(f"    Orders confirmed: {result['orders_confirmed']}")
    print(f"    Total PnL (SOL): {result['total_pnl_sol']:.4f}")
    print(f"    Duration (ms): {result['simulation_duration_ms']}")

    # 9. Health report
    health = pipeline.get_health_report()
    print("[10] Source health report:")
    for src, h in health.get("sources", {}).items():
        print(f"    {src}: {h['status']} (latency: {h['latency_ms']:.0f} ms, error_rate: {h['error_rate']:.2%})")

    # 10. Write results
    summary = executor.get_summary()
    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "chain": args.chain,
        "dry_run": True,
        "sources": sources,
        "signals_raw": len(all_signals),
        "signals_filtered": len(filtered_signals),
        "trade_signals": len(trade_signals),
        "simulation_result": result,
        "summary": summary,
        "health_report": health,
    }

    output_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        args.output,
    )
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"[11] Results written to {output_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
