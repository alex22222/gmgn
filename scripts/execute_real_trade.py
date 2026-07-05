#!/usr/bin/env python3
"""CLI script for executing real-money trades on the GMGN platform.

This is the entry point for REAL on-chain trading.  Every trade requires
human confirmation (unless ``--auto-confirm`` is passed, which is dangerous).

Usage::

    # Execute a single trade from a signal
    python3 scripts/execute_real_trade.py \
        --token <token_address> \
        --amount 0.005 \
        --wallet <your_wallet_address>

    # Batch execute from a JSON file of signals
    python3 scripts/execute_real_trade.py \
        --signals-file data/signals.json \
        --wallet <your_wallet_address>

    # Dry-run preview (no real transaction)
    python3 scripts/execute_real_trade.py \
        --token <token_address> \
        --amount 0.005 \
        --dry-run

    # Check current mode
    python3 scripts/execute_real_trade.py --mode
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gmgn_monitor.execution_switch import ExecutionSwitch, TRADE_MODE_DRYRUN, TRADE_MODE_REAL
from gmgn_monitor.real_trade_executor import RealTradeExecutor, HUMAN_CONFIRMATION_REQUIRED
from gmgn_monitor.dry_run_executor import DryRunExecutor
from gmgn_monitor.trade_signal import TPOrder, SLOrder, TradeSignal
from gmgn_monitor.config_manager import ConfigManager


def build_demo_signal(token_address: str, amount_sol: float) -> TradeSignal:
    """Build a demo TradeSignal for the given token and amount."""
    from datetime import timedelta
    from uuid import uuid4
    from datetime import datetime

    return TradeSignal(
        signal_id=str(uuid4()),
        wallet_address="demo_wallet",
        target_token=token_address,
        signal_type="NEW_POSITION",
        urgency_score=80,
        confidence_score=75,
        quality_score=78,
        recommended_amount_sol=amount_sol,
        max_slippage_percent=30.0,
        priority_fee_sol=0.01,
        mev_protection="SECURE",
        tp_orders=(
            TPOrder(level=1, trigger_percent=100.0, sell_percent=50.0),
            TPOrder(level=2, trigger_percent=300.0, sell_percent=50.0),
        ),
        sl_order=SLOrder(trigger_percent=-65.0, sell_percent=100.0),
        expires_at=datetime.utcnow() + timedelta(minutes=10),
        chain="sol",
        received_at=datetime.utcnow(),
    )


def cmd_execute_single(args: argparse.Namespace) -> int:
    """Execute a single trade."""
    switch = ExecutionSwitch()

    if args.dry_run or switch.is_dryrun:
        print(f"\nℹ️  MODE: DRY-RUN (no real transactions)")
        print(f"   Trade mode: {switch.mode}")
        print(f"   Token:      {args.token}")
        print(f"   Amount:     {args.amount:.6f} SOL")
        print(f"   Wallet:     {args.wallet or 'NOT SET'}")
        print()

        executor = DryRunExecutor(initial_balance_sol=10.0)
        signal = build_demo_signal(args.token, args.amount)
        result = executor.run_simulation([signal])
        print(f"Dry-run result: {result}")
        return 0

    # REAL MONEY MODE
    print(f"\n{'=' * 60}")
    print(f"⚠️  REAL MONEY MODE")
    print(f"{'=' * 60}")
    print(f"Token:   {args.token}")
    print(f"Amount:  {args.amount:.6f} SOL")
    print(f"Wallet:  {args.wallet or 'NOT SET'}")
    print(f"{'=' * 60}")

    if not args.wallet:
        print("\n❌ Error: --wallet is required for real-money trading")
        return 1

    executor = RealTradeExecutor(
        wallet_address=args.wallet,
        chain="sol",
        auto_confirm=args.auto_confirm,
    )

    signal = build_demo_signal(args.token, args.amount)
    result = executor.execute_trade(signal)

    print(f"\n{'=' * 60}")
    if result.success:
        print(f"✅ Trade executed successfully!")
        print(f"   Order ID: {result.order_id}")
        print(f"   TX Hash:  {result.tx_hash}")
        print(f"   Gas:      {result.gas_cost_sol:.6f} SOL")
        print(f"   Time:     {result.confirmation_time_ms:.0f} ms")
    else:
        print(f"❌ Trade failed!")
        print(f"   Error: {result.error_message}")
    print(f"{'=' * 60}")

    return 0 if result.success else 1


def cmd_batch(args: argparse.Namespace) -> int:
    """Execute a batch of trades from a JSON file."""
    switch = ExecutionSwitch()

    with open(args.signals_file, "r", encoding="utf-8") as f:
        signals_data = json.load(f)

    if not isinstance(signals_data, list):
        signals_data = [signals_data]

    print(f"\nLoaded {len(signals_data)} signals from {args.signals_file}")

    if switch.is_dryrun or args.dry_run:
        print(f"ℹ️  Running in DRY-RUN mode")
        executor = DryRunExecutor(initial_balance_sol=10.0)
        # Convert dict signals to TradeSignal objects
        signals = [TradeSignal(**s) for s in signals_data]
        result = executor.run_simulation(signals)
        print(f"Dry-run batch result: {json.dumps(result, indent=2, default=str)}")
        return 0

    # REAL MONEY
    print(f"⚠️  REAL MONEY BATCH — {len(signals_data)} trades")
    if not args.wallet:
        print("❌ Error: --wallet is required for real-money trading")
        return 1

    executor = RealTradeExecutor(
        wallet_address=args.wallet,
        chain="sol",
        auto_confirm=args.auto_confirm,
    )

    successes = 0
    failures = 0
    for i, sig_data in enumerate(signals_data, 1):
        print(f"\n--- Trade {i}/{len(signals_data)} ---")
        signal = TradeSignal(**sig_data)
        result = executor.execute_trade(signal)
        if result.success:
            successes += 1
        else:
            failures += 1

    print(f"\n{'=' * 60}")
    print(f"Batch complete: {successes} success, {failures} failure")
    print(f"{'=' * 60}")
    return 0 if failures == 0 else 1


def cmd_mode(args: argparse.Namespace) -> int:
    """Show current execution mode."""
    switch = ExecutionSwitch()
    print(f"Current trade mode: {switch.mode}")
    if switch.is_dryrun:
        print("  → Dry-run mode (no real transactions)")
    else:
        print("  → REAL MONEY mode (transactions go on-chain)")
    print()
    print("To switch mode:")
    print(f"  export GMGN_TRADE_MODE={TRADE_MODE_DRYRUN}   # Dry-run")
    print(f"  export GMGN_TRADE_MODE={TRADE_MODE_REAL}     # Real money")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Execute real-money trades on the GMGN platform",
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Single trade
    single_parser = subparsers.add_parser("single", help="Execute a single trade")
    single_parser.add_argument("--token", required=True, help="Target token address")
    single_parser.add_argument("--amount", type=float, required=True, help="Amount in SOL")
    single_parser.add_argument("--wallet", help="Your Solana wallet address")
    single_parser.add_argument("--dry-run", action="store_true", help="Preview without executing")
    single_parser.add_argument("--auto-confirm", action="store_true", help="Skip human confirmation (DANGEROUS)")
    single_parser.set_defaults(func=cmd_execute_single)

    # Batch trade
    batch_parser = subparsers.add_parser("batch", help="Execute trades from a JSON file")
    batch_parser.add_argument("--signals-file", required=True, help="Path to JSON file with signals")
    batch_parser.add_argument("--wallet", help="Your Solana wallet address")
    batch_parser.add_argument("--dry-run", action="store_true", help="Preview without executing")
    batch_parser.add_argument("--auto-confirm", action="store_true", help="Skip human confirmation (DANGEROUS)")
    batch_parser.set_defaults(func=cmd_batch)

    # Mode check
    mode_parser = subparsers.add_parser("mode", help="Show current execution mode")
    mode_parser.set_defaults(func=cmd_mode)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
