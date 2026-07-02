from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator


def load_json(path: Path, *, label: str | None = None) -> Any:
    """Load and parse a JSON file, raising ValueError with a clear path on failure.

    The optional *label* customizes error messages (e.g. "threshold config").
    """
    label = label or 'JSON'
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except UnicodeDecodeError as exc:
        raise ValueError(f'{path}: invalid {label} UTF-8: {exc.reason}') from exc
    except OSError as exc:
        raise ValueError(f'{path}: invalid {label} read: {exc}') from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f'{path}:{exc.lineno}: invalid {label} JSON: {exc.msg}') from exc


def load_jsonl(path: Path, *, label: str | None = None, object_label: str = 'record') -> Iterator[dict[str, Any]]:
    """Yield JSON objects from a JSONL file.

    Raises ValueError with line numbers for malformed lines.
    The optional *label* customizes error messages.
    """
    label = label or 'JSONL'
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError(f'{path}: invalid {label} UTF-8: {exc.reason}') from exc
    except OSError as exc:
        raise ValueError(f'{path}: invalid {label} read: {exc}') from exc
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f'{path}:{line_number}: invalid {label} JSON: {exc}') from exc
        if not isinstance(record, dict):
            raise ValueError(f'{path}:{line_number}: invalid {label} {object_label}: expected object')
        yield record
