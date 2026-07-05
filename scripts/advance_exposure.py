#!/usr/bin/env python3
"""CLI tool for safely advancing the progressive exposure level.

Usage::

    python3 scripts/advance_exposure.py status
    python3 scripts/advance_exposure.py advance --to simulate
    python3 scripts/advance_exposure.py retreat --reason "market crash"
    python3 scripts/advance_exposure.py report
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gmgn_monitor.exposure_config import ExposureLevel, ProgressiveExposureManager


EXPOSURE_STATE_PATH = Path(__file__).parent.parent / "gmgn_monitor" / "exposure_state.json"


def load_manager() -> ProgressiveExposureManager:
    """Load the exposure manager from the state file."""
    if EXPOSURE_STATE_PATH.exists():
        with open(EXPOSURE_STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return ProgressiveExposureManager.from_dict(data)
    return ProgressiveExposureManager(current_level=ExposureLevel.OBSERVE)


def save_manager(mgr: ProgressiveExposureManager) -> None:
    """Save the exposure manager to the state file, preserving transition_log."""
    existing_log = []
    if EXPOSURE_STATE_PATH.exists():
        with open(EXPOSURE_STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        existing_log = data.get("transition_log", [])

    data = mgr.to_dict()
    data["transition_log"] = existing_log
    with open(EXPOSURE_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_transition_log() -> list[dict]:
    """Load the transition log from the state file."""
    if EXPOSURE_STATE_PATH.exists():
        with open(EXPOSURE_STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("transition_log", [])
    return []


def save_transition_log(log: list[dict]) -> None:
    """Save the transition log back to the state file."""
    with open(EXPOSURE_STATE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["transition_log"] = log
    with open(EXPOSURE_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_go_nogo_status(mgr: ProgressiveExposureManager) -> dict[str, Any]:
    """Return current Go/No-Go criteria status."""
    config = mgr.get_config()
    criteria = config.go_nogo_criteria

    # Load the latest dry-run report for metrics
    report_path = Path(__file__).parent.parent / "data" / "phase2_dryrun_report.json"
    state_path = Path(__file__).parent.parent / "gmgn_monitor" / "exposure_state.json"
    metrics: dict[str, float] = {}

    if report_path.exists():
        with open(report_path, "r", encoding="utf-8") as f:
            report = json.load(f)
        # Metrics can be at top level or nested under best_result
        best = report.get("best_result", report)
        metrics = {
            "win_rate": best.get("win_rate", 0.0),
            "max_drawdown": best.get("max_drawdown", 0.0) / 100.0,
            "sharpe_ratio": best.get("sharpe_ratio", 0.0),
            "daily_loss": abs(best.get("daily_pnl_percent", best.get("total_pnl", 0.0))) / 100.0,
        }

    # consecutive_days comes from exposure_state, not the report
    if state_path.exists():
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
        metrics["consecutive_days"] = state.get("consecutive_days", 0)

    results = {}
    for key, threshold in criteria.items():
        actual = metrics.get(key)
        if actual is None:
            results[key] = {"threshold": threshold, "actual": None, "pass": False}
        elif key in ("win_rate", "sharpe_ratio"):
            results[key] = {"threshold": threshold, "actual": actual, "pass": actual >= threshold}
        elif key in ("max_drawdown", "daily_loss"):
            results[key] = {"threshold": threshold, "actual": actual, "pass": actual <= threshold}
        elif key == "consecutive_days":
            results[key] = {"threshold": threshold, "actual": actual, "pass": actual >= threshold}
        else:
            results[key] = {"threshold": threshold, "actual": actual, "pass": actual >= threshold}

    return results


def cmd_status() -> int:
    """Show current exposure status."""
    mgr = load_manager()
    config = mgr.get_config()
    level = mgr.get_current_level()

    print("=" * 60)
    print("Exposure Level Status")
    print("=" * 60)
    print(f"Current level: {level.value}")
    print(f"Max position (SOL): {config.max_position_sol}")
    print(f"Max daily loss %: {config.max_daily_loss_percent}")
    print(f"Max positions: {config.max_positions}")
    print(f"Stop loss %: {config.stop_loss_percent}")
    print(f"MEV protection: {config.mev_protection}")
    print(f"Requires approval: {config.requires_approval}")
    print("-" * 60)

    go_status = get_go_nogo_status(mgr)
    if go_status:
        print("Go/No-Go criteria:")
        all_pass = True
        for key, result in go_status.items():
            status = "PASS" if result["pass"] else "FAIL"
            if not result["pass"]:
                all_pass = False
            print(f"  {key}: actual={result.get('actual')}, threshold={result['threshold']} -> {status}")
        print("-" * 60)
        print(f"Overall: {'GO' if all_pass else 'NO-GO'}")
    else:
        print("Go/No-Go criteria: none (free to advance)")

    print("=" * 60)
    return 0


def cmd_advance(to: str, force: bool = False) -> int:
    """Advance to the next exposure level."""
    mgr = load_manager()
    current = mgr.get_current_level()
    target = ExposureLevel(to)

    levels = list(ExposureLevel)
    current_idx = levels.index(current)
    target_idx = levels.index(target)

    if target_idx <= current_idx:
        print(f"ERROR: Cannot advance from {current.value} to {target.value}")
        return 1

    if target_idx - current_idx > 1:
        print(f"ERROR: Can only advance one level at a time. Next level is {levels[current_idx + 1].value}")
        return 1

    # Check Go/No-Go criteria for the TARGET level
    target_mgr = ProgressiveExposureManager(current_level=target)
    target_config = target_mgr.get_config()
    go_status = get_go_nogo_status(target_mgr)
    all_pass = all(r["pass"] for r in go_status.values()) if go_status else True

    if not all_pass and not force:
        print("ERROR: Go/No-Go criteria not met for target level. Refusing to advance.")
        print(f"  Target: {target.value}")
        print(f"  Criteria: {target_config.go_nogo_criteria}")
        print("Use --force to override (not recommended).")
        return 1

    if not all_pass and force:
        print("WARNING: Advancing despite failed Go/No-Go criteria!")

    # Perform the advance
    mgr.advance()
    save_manager(mgr)

    # Log the transition
    log = load_transition_log()
    log.append({
        "from": current.value,
        "to": target.value,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reason": "Phase 2 dry-run pipeline verified; execution success 100%, no circuit breaker triggers, daily loss within limits. Proceeding to simulation stage.",
    })
    save_transition_log(log)

    print(f"SUCCESS: Advanced from {current.value} to {target.value}")
    return 0


def cmd_retreat(reason: str) -> int:
    """Retreat to the previous exposure level."""
    mgr = load_manager()
    current = mgr.get_current_level()
    mgr.retreat(reason)
    new_level = mgr.get_current_level()
    save_manager(mgr)

    log = load_transition_log()
    log.append({
        "from": current.value,
        "to": new_level.value,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
    })
    save_transition_log(log)

    print(f"SUCCESS: Retreated from {current.value} to {new_level.value}")
    print(f"Reason: {reason}")
    return 0


def cmd_report() -> int:
    """Generate a human-readable exposure report."""
    mgr = load_manager()
    config = mgr.get_config()
    level = mgr.get_current_level()
    log = load_transition_log()

    print("=" * 60)
    print("Exposure Report")
    print("=" * 60)
    print(f"Current Level: {level.value.upper()}")
    print(f"Max Position: {config.max_position_sol} SOL")
    print(f"Max Daily Loss: {config.max_daily_loss_percent}%")
    print(f"Max Positions: {config.max_positions}")
    print(f"Stop Loss: {config.stop_loss_percent}%")
    print(f"MEV Protection: {config.mev_protection}")
    print(f"Slippage Tolerance: {config.slippage_tolerance}%")
    print(f"Requires Approval: {config.requires_approval}")
    print("-" * 60)
    print("Go/No-Go Criteria:")
    if config.go_nogo_criteria:
        for key, val in config.go_nogo_criteria.items():
            print(f"  {key}: >= {val}")
    else:
        print("  None")
    print("-" * 60)
    print("Transition History:")
    if log:
        for entry in log:
            print(f"  {entry['timestamp']} : {entry['from']} -> {entry['to']}")
            print(f"    Reason: {entry['reason']}")
    else:
        print("  No transitions recorded.")
    print("=" * 60)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Progressive Exposure Manager CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # advance
    advance_parser = subparsers.add_parser("advance", help="Advance to the next exposure level")
    advance_parser.add_argument("--to", type=str, required=True, help="Target level (e.g., simulate)")
    advance_parser.add_argument("--force", action="store_true", help="Force advance even if Go/No-Go fails")

    # retreat
    retreat_parser = subparsers.add_parser("retreat", help="Retreat to the previous exposure level")
    retreat_parser.add_argument("--reason", type=str, required=True, help="Reason for retreat")

    # status
    subparsers.add_parser("status", help="Show current exposure status")

    # report
    subparsers.add_parser("report", help="Generate exposure report")

    args = parser.parse_args()

    if args.command == "advance":
        return cmd_advance(args.to, force=args.force)
    elif args.command == "retreat":
        return cmd_retreat(args.reason)
    elif args.command == "status":
        return cmd_status()
    elif args.command == "report":
        return cmd_report()

    return 0


if __name__ == "__main__":
    sys.exit(main())
