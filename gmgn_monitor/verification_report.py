from __future__ import annotations

import json
from pathlib import Path


def load_verification_report(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        report = json.loads(path.read_text(encoding='utf-8'))
    except UnicodeDecodeError as exc:
        raise ValueError(f'invalid verification report UTF-8: {exc.reason}') from exc
    except OSError as exc:
        raise ValueError(f'invalid verification report read: {exc}') from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f'invalid verification report JSON: {exc}') from exc
    if not isinstance(report, dict):
        raise ValueError('invalid verification report: expected object')
    return report


def report_matches_latest_history(report: dict[str, object] | None, history_records: list[dict[str, object]]) -> bool | None:
    if not isinstance(report, dict) or not history_records:
        return None
    latest = history_records[-1]
    current_fields = (
        'generated_at',
        'status',
        'steps',
        'operational_summary',
        'config_fingerprints',
        'artifact_fingerprints',
    )
    return all(report.get(field) == latest.get(field) for field in current_fields)
