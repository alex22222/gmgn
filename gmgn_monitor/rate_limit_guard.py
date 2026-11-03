"""Remember a GMGN account ban and refuse new reads until it lifts."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .file_io import atomic_write_text

_RESET_AT_RE = re.compile(r"resets at (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_SHANGHAI = timezone(timedelta(hours=8))
_DEFAULT_COOLDOWN = timedelta(minutes=5)


def cooldown_path(root: Path) -> Path:
    return root / "data" / "gmgn_rate_limit.json"


def is_rate_limited(message: str) -> bool:
    text = message.upper()
    return "429" in text or "RATE_LIMIT" in text


def parse_reset_at(message: str) -> datetime | None:
    match = _RESET_AT_RE.search(message)
    if match is None:
        return None
    parsed = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
    return parsed.replace(tzinfo=timezone.utc)


def read_reset_at(path: Path, now: datetime | None = None) -> datetime | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    raw = payload.get("reset_at")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    if moment <= current:
        return None
    return moment


def remember_rate_limit(path: Path, message: str, now: datetime | None = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    reset = parse_reset_at(message) or (current + _DEFAULT_COOLDOWN)
    existing = read_reset_at(path, current)
    if existing is not None and existing > reset:
        reset = existing
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        json.dumps({"reset_at": reset.isoformat()}, ensure_ascii=False) + "\n",
        path,
    )
    return reset


def blocked_notice(reset_at: datetime) -> str:
    local = reset_at.astimezone(_SHANGHAI)
    return f"GMGN 持仓接口限流，{local.strftime('%H:%M')}（北京时间）后再读。解禁前不会重复请求。"
