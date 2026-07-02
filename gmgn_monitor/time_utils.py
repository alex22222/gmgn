from __future__ import annotations

from datetime import datetime


def is_iso_timestamp(value: str) -> bool:
    """Return True if value is a valid ISO 8601 timestamp.

    Accepts the trailing 'Z' UTC suffix used by many APIs.
    """
    normalized = value[:-1] + '+00:00' if value.endswith('Z') else value
    try:
        datetime.fromisoformat(normalized)
    except ValueError:
        return False
    return True
