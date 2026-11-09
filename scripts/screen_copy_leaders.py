#!/usr/bin/env python3
"""Screen scored leaders for the manual copy-review queue.

Reads wallets already scored above 60, checks recent round trips and 30-day
stats, and writes data/copy_leader_review.json. It does not change
config/wallet_whitelist.json and does not enable follow.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from gmgn_monitor.copy_leader_fit import (  # noqa: E402
    MIN_CLOSED_TRIPS,
    build_copy_review,
    load_scored_leaders,
    measure_round_trips,
    write_copy_review,
)
from gmgn_monitor.paper_copy import (  # noqa: E402
    find_gmgn_cli,
    parse_activity_payload,
    parse_reset_at,
)


_PAGE_LIMIT = 50
_MAX_PAGES = 2
_PACE_SECONDS = 2.0


def main() -> int:
    root = _PROJECT_ROOT
    records = load_scored_leaders(root)
    labels = _follow_labels(root)
    for record in records:
        record["label"] = labels.get(str(record.get("wallet_address") or "").lower(), "")
    print(f"scored above 60: {len(records)}", flush=True)
    env = _gmgn_env()
    cli = find_gmgn_cli()
    stats_by_address, stats_error = _load_stats(cli, env, [str(item["wallet_address"]) for item in records])
    if stats_error:
        print(f"stats unavailable: {stats_error}", flush=True)

    activities: dict[str, list[dict[str, Any]]] = {}
    profits: dict[str, float] = {}
    tags: dict[str, list[str]] = {}
    ready: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []
    for record in records:
        address = str(record["wallet_address"])
        if stats_error or address not in stats_by_address:
            unavailable.append(_unavailable(record, stats_error or "30d stats missing"))
            continue
        profit, wallet_tags = stats_by_address[address]
        fetched, error = _load_activities(cli, env, address)
        if error:
            unavailable.append(_unavailable(record, error))
            continue
        activities[address] = fetched
        if profit is not None:
            profits[address] = profit
        tags[address] = wallet_tags
        ready.append(record)
        closed = sum(1 for trip in measure_round_trips(fetched) if trip["closed"])
        print(f"fetched {address[:4]}…{address[-4:]} closed={closed} tags={','.join(wallet_tags) or '-'}", flush=True)

    review = build_copy_review(ready, activities, tags_by_address=tags, profit_by_address=profits)
    review["unavailable"] = unavailable
    review["confirmed"] = []
    _mark_current_follow(root, review)
    path = write_copy_review(root, review)
    print(
        f"wrote {path} pending={review['pending_count']} rejected={review['rejected_count']} unavailable={len(unavailable)}",
        flush=True,
    )
    return 0


def _follow_labels(root: Path) -> dict[str, str]:
    payload = _read_whitelist(root)
    labels: dict[str, str] = {}
    for wallet in payload.get("wallets", []):
        if not isinstance(wallet, dict):
            continue
        address = str(wallet.get("wallet_address") or "").lower()
        if address:
            labels[address] = str(wallet.get("label") or "")
    return labels


def _mark_current_follow(root: Path, review: dict[str, Any]) -> None:
    payload = _read_whitelist(root)
    following: dict[str, str] = {}
    for wallet in payload.get("wallets", []):
        if not isinstance(wallet, dict):
            continue
        if not wallet.get("enabled") or str(wallet.get("mode") or "") != "follow":
            continue
        address = str(wallet.get("wallet_address") or "").lower()
        if address:
            following[address] = str(wallet.get("label") or "")
    for key in ("pending", "rejected", "excluded", "unavailable", "confirmed"):
        rows = review.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            address = str(row.get("wallet_address") or "").lower()
            row["current_follow"] = address in following
            row["current_label"] = following.get(address) or str(row.get("label") or "")


def _read_whitelist(root: Path) -> dict[str, Any]:
    path = root / "config/wallet_whitelist.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _unavailable(record: dict[str, Any], error: str) -> dict[str, Any]:
    return {
        "wallet_address": record.get("wallet_address"),
        "label": record.get("label") or "",
        "total_score": record.get("total_score"),
        "grade": record.get("grade"),
        "status": "unavailable",
        "error": error,
        "current_follow": False,
        "follow_enabled": False,
        "copy_fit": {},
    }


def _gmgn_env() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("GMGN_PRIVATE_KEY", None)
    key = _api_key()
    if key:
        env["GMGN_API_KEY"] = key
    return env


def _api_key() -> str:
    path = Path.home() / ".config" / "gmgn" / ".env"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in lines:
        if line.startswith("GMGN_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _load_stats(
    cli: str,
    env: dict[str, str],
    addresses: list[str],
) -> tuple[dict[str, tuple[float | None, list[str]]], str]:
    """Read 30-day stats one wallet at a time.

    A multi-wallet stats call comes back as one object, so it cannot be
    assigned to the right leader.
    """
    parsed: dict[str, tuple[float | None, list[str]]] = {}
    for address in addresses:
        command = [
            cli,
            "portfolio",
            "stats",
            "--chain",
            "sol",
            "--period",
            "30d",
            "--wallet",
            address,
            "--raw",
        ]
        payload, error = _run_json(command, env)
        if error or not isinstance(payload, (dict, list)):
            print(f"stats {address[:4]}…{address[-4:]} failed: {error or 'empty'}", flush=True)
            continue
        one = _parse_stats(payload, [address])
        if address not in one:
            print(f"stats {address[:4]}…{address[-4:]} missing profit", flush=True)
            continue
        parsed[address] = one[address]
        profit, wallet_tags = one[address]
        print(
            f"stats {address[:4]}…{address[-4:]} profit={profit} tags={','.join(wallet_tags) or '-'}",
            flush=True,
        )
    return parsed, ""


def _parse_stats(
    payload: Any,
    addresses: list[str],
) -> dict[str, tuple[float | None, list[str]]]:
    data = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload
    rows: list[dict[str, Any]]
    if isinstance(data, list):
        rows = [item for item in data if isinstance(item, dict)]
    elif isinstance(data, dict):
        nested = data.get("list") or data.get("wallets") or data.get("stats")
        if isinstance(nested, list):
            rows = [item for item in nested if isinstance(item, dict)]
        else:
            rows = [data]
    else:
        rows = []
    by_address: dict[str, dict[str, Any]] = {}
    for row in rows:
        found = str(row.get("wallet_address") or row.get("address") or "").lower()
        if found:
            by_address[found] = row
    if len(rows) == 1 and len(addresses) == 1 and addresses[0].lower() not in by_address:
        by_address[addresses[0].lower()] = rows[0]
    parsed: dict[str, tuple[float | None, list[str]]] = {}
    for address in addresses:
        row = by_address.get(address.lower())
        if row is None and len(addresses) == 1 and rows:
            row = rows[0]
        if row is None:
            continue
        profit = _profit(row)
        common = row.get("common") if isinstance(row.get("common"), dict) else {}
        raw_tags = common.get("tags") if isinstance(common, dict) else None
        if not isinstance(raw_tags, list):
            raw_tags = row.get("tags") if isinstance(row.get("tags"), list) else []
        parsed[address] = (profit, [str(tag) for tag in raw_tags])
    return parsed


def _profit(row: dict[str, Any]) -> float | None:
    for key in ("realized_profit", "realized_profit_30d"):
        try:
            return float(row[key])
        except (KeyError, TypeError, ValueError):
            continue
    return None


def _load_activities(
    cli: str,
    env: dict[str, str],
    address: str,
) -> tuple[list[dict[str, Any]], str]:
    rows: list[dict[str, Any]] = []
    cursor = ""
    last_error = ""
    for _page in range(_MAX_PAGES):
        command = [
            cli,
            "portfolio",
            "activity",
            "--chain",
            "sol",
            "--wallet",
            address,
            "--limit",
            str(_PAGE_LIMIT),
            "--type",
            "buy",
            "--type",
            "sell",
            "--raw",
        ]
        if cursor:
            command.extend(["--cursor", cursor])
        payload, error = _run_json(command, env)
        if error or payload is None:
            last_error = error or "activity response was empty"
            break
        rows.extend(parse_activity_payload(payload))
        closed = sum(1 for trip in measure_round_trips(rows) if trip["closed"])
        cursor = _next_cursor(payload)
        if closed >= MIN_CLOSED_TRIPS or not cursor:
            last_error = ""
            break
    if last_error and sum(1 for trip in measure_round_trips(rows) if trip["closed"]) < MIN_CLOSED_TRIPS:
        return [], last_error
    return rows, ""


def _next_cursor(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("next", "cursor"):
            value = payload.get(key)
            if value:
                return str(value)
        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("next", "cursor"):
                value = data.get(key)
                if value:
                    return str(value)
    return ""


def _run_json(command: list[str], env: dict[str, str]) -> tuple[Any, str]:
    for attempt in range(2):
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
            check=False,
        )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        message = (stderr or stdout).strip()
        if completed.returncode == 0:
            try:
                payload = json.loads(stdout)
            except json.JSONDecodeError:
                return None, "gmgn-cli returned invalid JSON"
            time.sleep(_PACE_SECONDS)
            return payload, ""
        if "429" in message or "RATE_LIMIT" in message:
            if attempt == 0:
                _sleep_until_reset(message)
                continue
            return None, _public_error(message)
        return None, _public_error(message)
    return None, "gmgn-cli failed"


def _sleep_until_reset(message: str) -> None:
    reset_at = parse_reset_at(message)
    if reset_at is None:
        time.sleep(5)
        return
    wait = reset_at.timestamp() - time.time() + 1
    time.sleep(max(1.0, min(wait, 300.0)))


def _public_error(message: str) -> str:
    compact = " ".join(message.split())
    return compact[:240]


if __name__ == "__main__":
    raise SystemExit(main())
