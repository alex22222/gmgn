from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from .serialization import load_jsonl
from .verification_expectations import check_operational_expectations
from .verification_steps import report_has_required_steps, report_status_matches_steps


def load_history(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return list(load_jsonl(path, label='history', object_label='record'))


def select_recent_records(records: list[dict[str, object]], limit: int | None) -> list[dict[str, object]]:
    if limit is None:
        return records
    if limit <= 0:
        raise ValueError('history limit must be positive')
    return records[-limit:]


def parse_generated_at(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp


def build_history_summary(records: list[dict[str, object]], now: datetime | None = None) -> dict[str, object]:
    now = now or datetime.now(timezone.utc)
    if not records:
        return {
            'consecutive_failure_count': 0,
            'failure_count': 0,
            'future_timestamp_count': 0,
            'incomplete_step_record_count': 0,
            'invalid_timestamp_count': 0,
            'last_record_status_matches_steps': None,
            'last_record_timestamp_future': None,
            'last_record_steps_complete': None,
            'last_record_timestamp_valid': None,
            'last_generated_at': None,
            'last_status': None,
            'last_success_generated_at': None,
            'last_step_statuses': {},
            'out_of_order_timestamp_count': 0,
            'record_count': 0,
            'status_counts': {},
            'status_step_mismatch_count': 0,
            'step_failure_counts': {},
        }

    latest = records[-1]
    consecutive_failure_count = 0
    last_success_generated_at = None
    status_counts: dict[str, int] = {}
    step_failure_counts: dict[str, int] = {}
    incomplete_step_record_count = 0
    invalid_timestamp_count = 0
    future_timestamp_count = 0
    status_step_mismatch_count = 0
    out_of_order_timestamp_count = 0
    previous_timestamp: datetime | None = None
    for record in records:
        timestamp = parse_generated_at(record.get('generated_at'))
        if timestamp is None:
            invalid_timestamp_count += 1
        else:
            if timestamp > now:
                future_timestamp_count += 1
            if previous_timestamp is not None and timestamp < previous_timestamp:
                out_of_order_timestamp_count += 1
            previous_timestamp = timestamp
        status = str(record.get('status'))
        status_counts[status] = status_counts.get(status, 0) + 1
        if record.get('status') == 'ok':
            last_success_generated_at = record.get('generated_at')
        if report_has_required_steps(record) is not True:
            incomplete_step_record_count += 1
        if report_status_matches_steps(record) is False:
            status_step_mismatch_count += 1
        for step in record.get('steps', []):
            if not isinstance(step, dict):
                continue
            if step.get('status') == 'ok':
                continue
            name = str(step.get('name'))
            step_failure_counts[name] = step_failure_counts.get(name, 0) + 1
    for record in reversed(records):
        if record.get('status') == 'ok':
            break
        consecutive_failure_count += 1

    return {
        'consecutive_failure_count': consecutive_failure_count,
        'failure_count': sum(1 for record in records if record.get('status') != 'ok'),
        'future_timestamp_count': future_timestamp_count,
        'incomplete_step_record_count': incomplete_step_record_count,
        'invalid_timestamp_count': invalid_timestamp_count,
        'last_record_status_matches_steps': report_status_matches_steps(latest),
        'last_record_timestamp_future': _is_future_timestamp(latest.get('generated_at'), now),
        'last_record_steps_complete': report_has_required_steps(latest),
        'last_record_timestamp_valid': parse_generated_at(latest.get('generated_at')) is not None,
        'last_generated_at': latest.get('generated_at'),
        'last_operational_summary': latest.get('operational_summary', {}),
        'last_status': latest.get('status'),
        'last_success_generated_at': last_success_generated_at,
        'last_step_statuses': {
            str(step.get('name')): step.get('status')
            for step in latest.get('steps', [])
            if isinstance(step, dict)
        },
        'out_of_order_timestamp_count': out_of_order_timestamp_count,
        'record_count': len(records),
        'status_counts': status_counts,
        'status_step_mismatch_count': status_step_mismatch_count,
        'step_failure_counts': step_failure_counts,
    }


def check_history_integrity(
    records: list[dict[str, object]],
    operational_expectations: dict[str, object] | None = None,
    now: datetime | None = None,
) -> list[str]:
    failures: list[str] = []
    now = now or datetime.now(timezone.utc)
    previous_timestamp: datetime | None = None
    for index, record in enumerate(records, start=1):
        if record.get('status') not in ('ok', 'fail'):
            failures.append(f'invalid verification history status at line {index}')
        if report_has_required_steps(record) is not True:
            failures.append(f'incomplete verification history steps at line {index}')
        if report_status_matches_steps(record) is False:
            failures.append(f'verification history status mismatch with steps at line {index}')
        timestamp = parse_generated_at(record.get('generated_at'))
        if timestamp is None:
            failures.append(f'invalid verification history timestamp at line {index}')
            continue
        if timestamp > now:
            failures.append(f'future verification history timestamp at line {index}')
        if previous_timestamp is not None and timestamp < previous_timestamp:
            failures.append(f'out-of-order verification history timestamp at line {index}')
        previous_timestamp = timestamp
        if operational_expectations is not None:
            summary = record.get('operational_summary')
            if not isinstance(summary, dict):
                failures.append(f'invalid verification history operational summary at line {index}')
            else:
                for failure in check_operational_expectations(summary, operational_expectations):
                    failures.append(f'verification history operational summary mismatch at line {index}: {failure}')
    return failures


def format_history_summary(summary: dict[str, object]) -> str:
    lines = [
        '# GMGN Verification History',
        '',
        f"Records: {summary['record_count']}",
        f"Failures: {summary['failure_count']}",
        f"Incomplete step records: {summary.get('incomplete_step_record_count')}",
        f"Invalid timestamp records: {summary.get('invalid_timestamp_count')}",
        f"Status-step mismatch records: {summary.get('status_step_mismatch_count')}",
        f"Future timestamp records: {summary.get('future_timestamp_count')}",
        f"Out-of-order timestamp records: {summary.get('out_of_order_timestamp_count')}",
        f"Consecutive failures: {summary.get('consecutive_failure_count')}",
        f"Status counts: {summary.get('status_counts', {})}",
        f"Last status: {summary['last_status']}",
        f"Last record status matches steps: {summary.get('last_record_status_matches_steps')}",
        f"Last record steps complete: {summary.get('last_record_steps_complete')}",
        f"Last record timestamp valid: {summary.get('last_record_timestamp_valid')}",
        f"Last record timestamp future: {summary.get('last_record_timestamp_future')}",
        f"Last generated at: {summary['last_generated_at']}",
        f"Last success generated at: {summary.get('last_success_generated_at')}",
    ]
    step_failure_counts = summary.get('step_failure_counts')
    if isinstance(step_failure_counts, dict) and step_failure_counts:
        lines.extend([
            '',
            '## Step Failure Counts',
            '',
        ])
        for name, count in step_failure_counts.items():
            lines.append(f'- {name}: {count}')
    operational_summary = summary.get('last_operational_summary')
    if isinstance(operational_summary, dict) and operational_summary:
        lines.extend([
            '',
            '## Last Operational Summary',
            '',
            f"Automation gate: {operational_summary.get('automation_gate_status')}",
            f"Candidates: {operational_summary.get('candidate_count')}",
            f"Decisions: {operational_summary.get('decisions')}",
            f"Outcomes: {operational_summary.get('outcomes')}",
        ])
    step_statuses = summary.get('last_step_statuses')
    if isinstance(step_statuses, dict) and step_statuses:
        lines.extend(['', '## Last Steps', ''])
        for name, status in step_statuses.items():
            lines.append(f'- {name}: {status}')
    return '\n'.join(lines) + '\n'


def should_fail_summary(
    summary: dict[str, object],
    fail_on_any_failure: bool = False,
    require_complete_steps: bool = False,
    require_valid_timestamps: bool = False,
) -> bool:
    if fail_on_any_failure and summary.get('failure_count', 0) > 0:
        return True
    if require_complete_steps and summary.get('incomplete_step_record_count', 0) > 0:
        return True
    if require_complete_steps and summary.get('status_step_mismatch_count', 0) > 0:
        return True
    if require_valid_timestamps and (
        summary.get('invalid_timestamp_count', 0) > 0 or
        summary.get('future_timestamp_count', 0) > 0 or
        summary.get('out_of_order_timestamp_count', 0) > 0
    ):
        return True
    return summary.get('last_status') not in (None, 'ok')


def main() -> int:
    parser = argparse.ArgumentParser(description='Summarize local GMGN verification history.')
    parser.add_argument('--input', type=Path, default=Path('data/verification_history.jsonl'))
    parser.add_argument('--limit', type=int, help='Summarize only the most recent N records.')
    parser.add_argument('--fail-on-any-failure', action='store_true', help='Exit non-zero if any summarized record failed.')
    parser.add_argument('--require-complete-steps', action='store_true', help='Exit non-zero if any summarized record lacks the complete ok verification step set.')
    parser.add_argument('--require-valid-timestamps', action='store_true', help='Exit non-zero if any summarized record has an invalid, future, or out-of-order generated_at timestamp.')
    parser.add_argument('--json', action='store_true', help='Print machine-readable history summary.')
    args = parser.parse_args()

    try:
        records = select_recent_records(load_history(args.input), args.limit)
    except ValueError as exc:
        print(f'GMGN verification history: {exc}')
        return 1

    summary = build_history_summary(records)
    if args.json:
        print(json.dumps(summary, sort_keys=True))
    else:
        print(format_history_summary(summary), end='')
    return 1 if should_fail_summary(
        summary,
        args.fail_on_any_failure,
        args.require_complete_steps,
        args.require_valid_timestamps,
    ) else 0


def _is_future_timestamp(value: object, now: datetime) -> bool | None:
    timestamp = parse_generated_at(value)
    if timestamp is None:
        return None
    return timestamp > now


if __name__ == '__main__':
    raise SystemExit(main())
