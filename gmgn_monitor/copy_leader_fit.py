"""Decide whether a scored leader can be copied by the 90-second poller."""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .file_io import atomic_write_text


FAST_CLOSE_SECONDS = 90
MIN_MEDIAN_HOLD_SECONDS = 15 * 60
MAX_FAST_CLOSE_RATIO = 0.50
MIN_CLOSED_TRIPS = 8
MIN_REVIEW_SCORE = 60.0
REJECT_TAGS = frozenset({"wash_trader", "arbitrager"})
_AMOUNT_MATCH = 0.98


def assess_copy_fit(
    activities: list[dict[str, Any]],
    *,
    score: float,
    realized_profit: float | None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Return a review decision. Pending leaders are stored for a person to confirm.

    A leader is copyable when the score is above 60, realized profit is positive,
    the wallet is not tagged as wash trading or arbitrage, most recent round
    trips stay open longer than one poll, and the median hold is at least 15 minutes.
    """
    closed = [trip for trip in measure_round_trips(activities) if trip["closed"]]
    holds = [int(trip["hold_seconds"]) for trip in closed]
    fast_count = sum(1 for hold in holds if hold <= FAST_CLOSE_SECONDS)
    fast_ratio = (fast_count / len(holds)) if holds else None
    median_hold = int(statistics.median(holds)) if holds else None
    blocked_tags = sorted({tag for tag in (tags or []) if tag in REJECT_TAGS})
    reasons: list[str] = []
    if float(score) <= MIN_REVIEW_SCORE:
        reasons.append(f"score {float(score):.2f} <= {MIN_REVIEW_SCORE:.0f}")
    if realized_profit is None:
        reasons.append("missing realized profit")
    elif float(realized_profit) <= 0:
        reasons.append("realized profit is not positive after fees")
    if blocked_tags:
        reasons.append("tagged " + ", ".join(blocked_tags))
    if len(closed) < MIN_CLOSED_TRIPS:
        reasons.append(f"closed round trips {len(closed)} < {MIN_CLOSED_TRIPS}")
    else:
        if fast_ratio is not None and fast_ratio >= MAX_FAST_CLOSE_RATIO:
            reasons.append(
                f"{fast_count}/{len(holds)} round trips close within {FAST_CLOSE_SECONDS}s"
            )
        if median_hold is None or median_hold < MIN_MEDIAN_HOLD_SECONDS:
            reasons.append(
                f"median hold {median_hold or 0}s < {MIN_MEDIAN_HOLD_SECONDS}s"
            )
    fit = {
        "decision": "pending_confirmation" if not reasons else "rejected",
        "reasons": reasons,
        "closed_round_trips": len(closed),
        "fast_close_count": fast_count,
        "fast_close_ratio": None if fast_ratio is None else round(fast_ratio, 4),
        "median_hold_seconds": median_hold,
        "blocked_tags": blocked_tags,
    }
    fit["reasons_zh"] = explain_fit(fit)
    return fit


def explain_fit(fit: dict[str, Any]) -> list[str]:
    """Chinese reasons for the review table, derived from the stored decision."""
    explained: list[str] = []
    for reason in fit.get("reasons") or []:
        text = str(reason)
        if text.startswith("score "):
            explained.append(f"分数 {text.split()[1]} 没有超过 60")
        elif text == "missing realized profit":
            explained.append("没有已实现利润")
        elif text.startswith("realized profit"):
            explained.append("扣费后已实现利润不是正数")
        elif text.startswith("tagged "):
            explained.append("标签含 " + text.removeprefix("tagged "))
        elif "closed round trips" in text:
            explained.append(text.replace("closed round trips ", "完整回合 ").replace(" < ", " 笔，少于 ") + " 笔")
        elif "90s" in text:
            explained.append(f"{fit.get('fast_close_count')}/{fit.get('closed_round_trips')} 笔在 90 秒内平仓")
        elif text.startswith("median hold"):
            explained.append(f"中位持仓 {fit.get('median_hold_seconds') or 0} 秒，短于 15 分钟")
        elif "hard-rejected" in text:
            explained.append("评分阶段已被硬淘汰")
        else:
            explained.append(text)
    return explained


def load_scored_leaders(root: Path, *, min_score: float = MIN_REVIEW_SCORE) -> list[dict[str, Any]]:
    """Return deduped scored wallets whose total score is above the review floor."""
    chosen: dict[str, dict[str, Any]] = {}
    for name in ("whitelist_wallets.json", "watchlist_wallets.json", "blacklist_wallets.json"):
        path = root / "data" / name
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, list):
            continue
        for record in payload:
            if not isinstance(record, dict):
                continue
            address = str(record.get("wallet_address") or record.get("address") or "").strip()
            try:
                score = float(record.get("total_score"))
            except (TypeError, ValueError):
                continue
            if not address or score <= min_score:
                continue
            current = chosen.get(address.lower())
            if current is None or score > float(current.get("total_score") or 0):
                chosen[address.lower()] = {**record, "wallet_address": address, "score_source": name}
    return sorted(chosen.values(), key=lambda item: float(item.get("total_score") or 0), reverse=True)


def build_copy_review(
    records: list[dict[str, Any]],
    activities_by_address: dict[str, list[dict[str, Any]]],
    *,
    tags_by_address: dict[str, list[str]] | None = None,
    profit_by_address: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Classify scored leaders without changing the live follow list."""
    tags_by_address = tags_by_address or {}
    profit_by_address = profit_by_address or {}
    rows: list[dict[str, Any]] = []
    for record in records:
        address = str(record.get("wallet_address") or "")
        stats = record.get("stats") if isinstance(record.get("stats"), dict) else {}
        stored_profit = stats.get("realized_profit")
        profit = profit_by_address.get(address, stored_profit)
        try:
            profit_value = None if profit is None else float(profit)
        except (TypeError, ValueError):
            profit_value = None
        try:
            score = float(record.get("total_score"))
        except (TypeError, ValueError):
            score = 0.0
        tags = list(tags_by_address.get(address) or record.get("tags") or [])
        fit = assess_copy_fit(
            activities_by_address.get(address, []),
            score=score,
            realized_profit=profit_value,
            tags=[str(tag) for tag in tags],
        )
        if record.get("hard_rejected"):
            reasons = [str(reason) for reason in fit["reasons"]]
            note = "wallet was hard-rejected by the score filter"
            if note not in reasons:
                reasons.append(note)
            fit = {**fit, "decision": "rejected", "reasons": reasons}
        fit["reasons_zh"] = explain_fit(fit)
        pending = fit["decision"] == "pending_confirmation"
        filter_reasons = record.get("filter_reasons")
        rows.append(
            {
                "wallet_address": address,
                "label": str(record.get("label") or ""),
                "total_score": score,
                "grade": record.get("grade"),
                "hard_rejected": bool(record.get("hard_rejected")),
                "score_source": record.get("score_source"),
                "winrate": stats.get("winrate"),
                "realized_profit": profit_value,
                "trades_7d": stats.get("trades_7d"),
                "tags": [str(tag) for tag in tags],
                "filter_reasons": [str(item) for item in filter_reasons] if isinstance(filter_reasons, list) else [],
                "status": "pending_confirmation" if pending else "rejected",
                "copy_fit": fit,
                "follow_enabled": False,
                "current_follow": False,
                "confirmation": "needs_human" if pending else "not_offered",
            }
        )
    pending = [row for row in rows if row["status"] == "pending_confirmation"]
    rejected = [row for row in rows if row["status"] != "pending_confirmation"]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rules": {
            "min_score_exclusive": MIN_REVIEW_SCORE,
            "min_median_hold_seconds": MIN_MEDIAN_HOLD_SECONDS,
            "max_fast_close_ratio": MAX_FAST_CLOSE_RATIO,
            "fast_close_seconds": FAST_CLOSE_SECONDS,
            "min_closed_trips": MIN_CLOSED_TRIPS,
            "reject_tags": sorted(REJECT_TAGS),
            "auto_follow": False,
        },
        "pending_count": len(pending),
        "rejected_count": len(rejected),
        "pending": pending,
        "rejected": rejected,
    }


def write_copy_review(root: Path, review: dict[str, Any]) -> Path:
    path = root / "data" / "copy_leader_review.json"
    atomic_write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", path)
    return path


def measure_round_trips(activities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pair each buy with the later sells that close that inventory."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in activities:
        if not isinstance(entry, dict):
            continue
        token = _token_address(entry)
        if not token or _event_type(entry) not in {"buy", "sell"}:
            continue
        grouped.setdefault(token, []).append(entry)

    trips: list[dict[str, Any]] = []
    for token, entries in grouped.items():
        entries.sort(key=_timestamp)
        for index, entry in enumerate(entries):
            if _event_type(entry) != "buy":
                continue
            needed = _number(entry.get("token_amount"))
            if needed <= 0:
                continue
            bought_at = _timestamp(entry)
            filled = 0.0
            sell_sol = 0.0
            fee = _number(entry.get("gas_native"))
            closed_at = bought_at
            for later in entries[index + 1 :]:
                if _event_type(later) != "sell":
                    continue
                filled += _number(later.get("token_amount"))
                sell_sol += _number(later.get("quote_amount"))
                fee += _number(later.get("gas_native"))
                closed_at = _timestamp(later)
                if filled >= needed * _AMOUNT_MATCH:
                    break
            closed = filled >= needed * _AMOUNT_MATCH
            symbol = _symbol(entry)
            trips.append(
                {
                    "token": token,
                    "symbol": symbol,
                    "buy_time": bought_at,
                    "hold_seconds": max(0, closed_at - bought_at) if closed else None,
                    "closed": closed,
                    "buy_sol": _number(entry.get("quote_amount")),
                    "sell_sol": sell_sol if closed else None,
                    "fee_sol": fee if closed else None,
                }
            )
    return trips


def _event_type(entry: dict[str, Any]) -> str:
    return str(entry.get("event_type") or entry.get("type") or "").strip().lower()


def _token_address(entry: dict[str, Any]) -> str:
    token = entry.get("token")
    if isinstance(token, dict):
        return str(token.get("address") or token.get("token_address") or "")
    return str(entry.get("token_address") or "")


def _symbol(entry: dict[str, Any]) -> str:
    token = entry.get("token")
    if isinstance(token, dict) and token.get("symbol"):
        return str(token["symbol"])
    return ""


def _timestamp(entry: dict[str, Any]) -> int:
    try:
        raw = int(float(entry.get("timestamp") or 0))
    except (TypeError, ValueError):
        return 0
    if raw > 10_000_000_000:
        return raw // 1000
    return raw


def _number(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
