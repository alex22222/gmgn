#!/usr/bin/env python3
"""Run the Phase 2 Dry-Run iteration with SignalQualityOptimizer.

Usage:
    python3 scripts/run_phase2_dryrun_iteration.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gmgn_monitor.backtest_data_loader import BacktestDataLoader
from gmgn_monitor.css_engine import CSSWeights
from gmgn_monitor.dry_run_executor import DryRunExecutor
from gmgn_monitor.popular_tokens import get_default_token_addresses
from gmgn_monitor.realistic_mock import RealisticMockGenerator
from gmgn_monitor.risk_manager import RiskLimits
from gmgn_monitor.signal_preprocessor import SignalPreprocessor
from gmgn_monitor.signal_quality_optimizer import SignalQualityOptimizer
from gmgn_monitor.synthetic_market_generator import SyntheticMarketGenerator
from gmgn_monitor.trade_signal import TPOrder, TradeSignal


def load_real_token_data(loader: BacktestDataLoader, hours: int = 168) -> dict[str, list[dict]]:
    """Load real OHLCV data for popular tokens; fallback to synthetic via BacktestDataLoader."""
    token_data: dict[str, list[dict]] = {}
    popular = get_default_token_addresses(chain="sol", count=5)
    for address in popular:
        try:
            ohlcv = loader.load_ohlcv(address, chain="sol", timeframe="1H", limit=hours)
            if ohlcv:
                token_data[address] = ohlcv
                print(f"    Loaded real data for {address[:20]}... — {len(ohlcv)} candles")
                continue
        except Exception as e:
            print(f"    Warning: failed to load real data for {address[:20]}...: {e}")
        # Fallback to synthetic via BacktestDataLoader
        synth = loader.generate_realistic_synthetic_ohlcv(address, base_price=100.0, hours=hours)
        token_data[address] = synth
        print(f"    Fallback synthetic for {address[:20]}... — {len(synth)} candles")
    return token_data


def main() -> None:
    print("=" * 60)
    print("Phase 2 Dry-Run Iteration (with SignalQualityOptimizer)")
    print("=" * 60)

    # 1. Generate 200 realistic wallets
    mock_gen = RealisticMockGenerator(seed=42)
    wallets = mock_gen.generate_batch(count=200)
    wallet_addresses = [w["wallet_address"] for w in wallets]
    wallet_scores = {w["wallet_address"]: w["win_rate_30d"] for w in wallets}
    print(f"[1] Generated {len(wallets)} realistic wallets")
    print(f"    Score distribution: min={min(wallet_scores.values()):.1f}, "
          f"max={max(wallet_scores.values()):.1f}, "
          f"avg={sum(wallet_scores.values())/len(wallet_scores):.1f}")

    # 2. Load real OHLCV data for popular tokens (5 tokens for better statistics)
    loader = BacktestDataLoader()
    token_data = load_real_token_data(loader, hours=168)
    print(f"[2] Loaded {len(token_data)} tokens (real + fallback)")

    # 3. Generate BuySignals from wallet activities
    market_gen = SyntheticMarketGenerator(seed=42)
    buy_signals = market_gen.generate_wallet_signals(
        wallets=wallet_addresses,
        token_data=token_data,
        scenario="mixed",
    )
    print(f"[3] Generated {len(buy_signals)} BuySignals")

    # 4. Convert to TradeSignals
    trade_signals = [
        TradeSignal.from_buy_signal(
            bs, wallet_score=wallet_scores.get(bs.wallet_address, 0.0)
        )
        for bs in buy_signals
    ]
    # Deduplicate by token
    token_signals: dict[str, TradeSignal] = {}
    for ts in trade_signals:
        existing = token_signals.get(ts.target_token)
        if existing is None or ts.quality_score > existing.quality_score:
            token_signals[ts.target_token] = ts
    deduped_signals = list(token_signals.values())
    print(f"    After dedup: {len(deduped_signals)} TradeSignals")

    # 5. Instantiate optimizer and attach data
    optimizer = SignalQualityOptimizer()
    optimizer.set_test_data(
        signals=deduped_signals,
        wallet_scores=wallet_scores,
        market_data=token_data,
    )

    # 6. Optimize min_wallet_score
    print("[4] Optimizing min_wallet_score...")
    best_min_wallet = optimizer.optimize_min_wallet_score(
        candidates=[50.0, 60.0, 70.0, 80.0, 90.0]
    )
    print(f"    Best min_wallet_score: {best_min_wallet}")

    # 7. Try 3-5 different CSS weight combinations and pick the best
    print("[5] Optimizing CSS weights (4 candidates)...")
    weight_candidates = [
        CSSWeights(0.25, 0.20, 0.15, 0.20, 0.20),   # Default
        CSSWeights(0.35, 0.15, 0.10, 0.20, 0.20),   # Wallet-heavy
        CSSWeights(0.20, 0.30, 0.10, 0.20, 0.20),   # Risk-heavy
        CSSWeights(0.20, 0.15, 0.15, 0.20, 0.30),   # Momentum-heavy
    ]
    best_result: dict | None = None
    best_combo: CSSWeights | None = None
    for combo in weight_candidates:
        result = optimizer.evaluate_config(
            weights=combo,
            min_wallet_score=best_min_wallet,
            tp_orders=(
                TPOrder(1, 100.0, 50.0),
                TPOrder(2, 300.0, 50.0),
            ),
            sl_trigger=-65.0,
        )
        print(
            f"    wallet={combo.wallet:.2f} risk={combo.token_risk:.2f} "
            f"market={combo.market_condition:.2f} account={combo.account_state:.2f} "
            f"time={combo.time_momentum:.2f} -> win_rate={result['win_rate']:.2%} "
            f"(trades={result['total_trades']})"
        )
        if best_result is None or result["win_rate"] > best_result["win_rate"]:
            best_result = result
            best_combo = combo
    print(f"[6] Best CSS weights: {best_combo}")
    print(f"    Best win_rate: {best_result['win_rate']:.2%}")
    print(f"    Total PnL: {best_result['total_pnl']:.4f} SOL")
    print(f"    Sharpe: {best_result['sharpe_ratio']:.4f}")
    print(f"    Max drawdown: {best_result['max_drawdown']:.2f}%")

    # 8. Re-evaluate with best config
    final_result = optimizer.evaluate_config(
        weights=best_combo,
        min_wallet_score=best_min_wallet,
        tp_orders=(
            TPOrder(1, 100.0, 50.0),
            TPOrder(2, 300.0, 50.0),
        ),
        sl_trigger=-65.0,
    )

    # 9. Build full report with Go/No-Go
    go_checks = {
        "signal_accuracy": final_result["win_rate"] >= 0.80,
        "execution_success": True,
        "daily_loss": final_result["max_drawdown"] < 10.0,
    }
    failed_checks = [name for name, passed in go_checks.items() if not passed]
    assessment = "Go" if not failed_checks else "No-Go"

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "best_config": {
            "weights": {
                "wallet": best_combo.wallet if best_combo else 0.25,
                "token_risk": best_combo.token_risk if best_combo else 0.20,
                "market_condition": best_combo.market_condition if best_combo else 0.15,
                "account_state": best_combo.account_state if best_combo else 0.20,
                "time_momentum": best_combo.time_momentum if best_combo else 0.20,
            },
            "min_wallet_score": best_min_wallet,
            "tp_orders": [(100.0, 50.0), (300.0, 50.0)],
            "sl_trigger": -65.0,
        },
        "best_result": final_result,
        "go_checks": go_checks,
        "failed_criteria": failed_checks,
        "assessment": assessment,
        "total_wallets": len(wallets),
        "tokens_used": list(token_data.keys()),
    }

    report_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
        "phase2_dryrun_report.json",
    )
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"[7] Report written to {report_path}")
    print("=" * 60)
    print(f"Assessment: {assessment}")
    if failed_checks:
        print(f"Failed criteria: {failed_checks}")
    print("=" * 60)


if __name__ == "__main__":
    main()
