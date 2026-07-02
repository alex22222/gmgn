from __future__ import annotations

import json
from pathlib import Path


REQUIRED_DECISIONS = ('alert', 'watch', 'reject')
REQUIRED_OUTCOMES = ('pending', 'reviewed')


def load_verification_expectations(path: Path) -> dict[str, object]:
    try:
        expectations = json.loads(path.read_text(encoding='utf-8'))
    except UnicodeDecodeError as exc:
        raise ValueError(f'{path}: invalid verification expectations UTF-8: {exc.reason}') from exc
    except OSError as exc:
        raise ValueError(f'{path}: invalid verification expectations read: {exc}') from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f'{path}:{exc.lineno}: invalid verification expectations JSON: {exc.msg}') from exc
    failures = validate_verification_expectations(expectations)
    if failures:
        raise ValueError('; '.join(failures))
    return expectations


def validate_verification_expectations(expectations: dict[str, object]) -> list[str]:
    failures: list[str] = []
    _validate_string(expectations, 'automation_gate_status', failures)
    _validate_nonnegative_int(expectations, 'candidate_count', failures)
    _validate_count_group(expectations, 'decisions', REQUIRED_DECISIONS, failures)
    _validate_count_group(expectations, 'outcomes', REQUIRED_OUTCOMES, failures)
    return failures


def check_operational_expectations(summary: dict[str, object], expected: dict[str, object]) -> list[str]:
    failures: list[str] = []
    for key in ('automation_gate_status', 'candidate_count'):
        if key in expected and summary.get(key) != expected[key]:
            failures.append(f'{key} expected {expected[key]!r}, got {summary.get(key)!r}')
    for group_key in ('decisions', 'outcomes'):
        expected_group = expected.get(group_key)
        summary_group = summary.get(group_key)
        if isinstance(expected_group, dict):
            for key, value in expected_group.items():
                actual = summary_group.get(key) if isinstance(summary_group, dict) else None
                if actual != value:
                    failures.append(f'{group_key}.{key} expected {value!r}, got {actual!r}')
    return failures


def _validate_string(expectations: dict[str, object], key: str, failures: list[str]) -> None:
    if not isinstance(expectations.get(key), str):
        failures.append(f'{key} must be a string')


def _validate_nonnegative_int(expectations: dict[str, object], key: str, failures: list[str]) -> None:
    value = expectations.get(key)
    if not isinstance(value, int) or value < 0:
        failures.append(f'{key} must be a non-negative integer')


def _validate_count_group(
    expectations: dict[str, object],
    group_key: str,
    required_keys: tuple[str, ...],
    failures: list[str],
) -> None:
    group = expectations.get(group_key)
    if not isinstance(group, dict):
        failures.append(f'{group_key} must be an object')
        return
    for key in required_keys:
        value = group.get(key)
        if not isinstance(value, int) or value < 0:
            failures.append(f'{group_key}.{key} must be a non-negative integer')
