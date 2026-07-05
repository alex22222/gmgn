from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .file_io import durable_append_text


AUDIT_LOG_RELATIVE_PATH = Path("data/audit_events.jsonl")


def append_audit_event(
    root: Path,
    *,
    category: str,
    action: str,
    success: bool,
    source: str,
    actor: str = "system",
    object_type: str = "",
    object_id: str = "",
    message: str = "",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "category": category,
        "action": action,
        "success": bool(success),
        "status": "success" if success else "failed",
        "source": source,
        "actor": actor,
        "object_type": object_type,
        "object_id": object_id,
        "message": message,
        "details": _json_safe(details or {}),
    }
    durable_append_text(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n",
        root.resolve() / AUDIT_LOG_RELATIVE_PATH,
    )
    return record


def read_audit_events(root: Path, limit: int = 300) -> list[dict[str, Any]]:
    path = root.resolve() / AUDIT_LOG_RELATIVE_PATH
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    for line in lines[-max(1, limit):]:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def build_audit_report(root: Path, limit: int = 300) -> dict[str, Any]:
    events = read_audit_events(root, limit=limit)
    categories = {
        "manual_config": 0,
        "manual_trade": 0,
        "auto_trade": 0,
        "copy_trade": 0,
    }
    successes = 0
    failures = 0
    for event in events:
        category = str(event.get("category") or "")
        if category in categories:
            categories[category] += 1
        if event.get("success") is True:
            successes += 1
        else:
            failures += 1
    return {
        "path": str(AUDIT_LOG_RELATIVE_PATH),
        "total": len(events),
        "successes": successes,
        "failures": failures,
        "categories": categories,
        "recent_events": list(reversed(events[-100:])),
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
