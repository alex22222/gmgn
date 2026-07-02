from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from .doctor import run_checks
from .file_io import describe_lock, describe_temp_artifacts
from .history import build_history_summary, load_history, select_recent_records, should_fail_summary
from .verification_report import load_verification_report, report_matches_latest_history
from .verification_steps import report_has_required_steps


def build_status(
    root: Path = Path('.'),
    report_path: Path = Path('data/verification_report.json'),
    history_path: Path = Path('data/verification_history.jsonl'),
    max_report_age_minutes: int | None = None,
    history_limit: int | None = None,
    fail_on_any_history_failure: bool = False,
    require_history_complete_steps: bool = False,
    require_history_valid_timestamps: bool = False,
    require_history_current: bool = False,
    require_report: bool = False,
    fail_on_future_report: bool = False,
    fail_on_stale_lock: bool = False,
    fail_on_stale_temp_artifacts: bool = False,
    now: datetime | None = None,
) -> dict[str, object]:
    root = root.resolve()
    doctor_failures = run_checks(root)
    verification_lock = describe_lock(root / 'data/verification.lock')
    temp_artifacts = describe_temp_artifacts(root / 'data')
    report = load_verification_report(root / report_path)
    history_records = load_history(root / history_path)
    selected_history_records = select_recent_records(history_records, history_limit)
    history_summary = build_history_summary(selected_history_records, now)
    report_history_match = report_matches_latest_history(report, history_records)
    report_steps_complete = report_has_required_steps(report)

    report_status = report.get('status') if isinstance(report, dict) else None
    report_generated_at = report.get('generated_at') if isinstance(report, dict) else None
    report_age_minutes = calculate_report_age_minutes(report_generated_at, now)
    report_future_seconds = calculate_report_future_seconds(report_generated_at, now)
    status = 'ok'
    if doctor_failures or report_status not in (None, 'ok') or should_fail_summary(
        history_summary,
        fail_on_any_history_failure,
        require_history_complete_steps,
        require_history_valid_timestamps,
    ):
        status = 'fail'
    if max_report_age_minutes is not None and report_age_minutes is not None and report_age_minutes > max_report_age_minutes:
        status = 'fail'
    if require_history_current and report_history_match is not True:
        status = 'fail'
    if require_report and (
        report_status != 'ok' or
        report_age_minutes is None or
        report_future_seconds not in (0, None) or
        report_steps_complete is not True
    ):
        status = 'fail'
    if fail_on_future_report and report_future_seconds not in (0, None):
        status = 'fail'
    if fail_on_stale_lock and verification_lock.get('stale'):
        status = 'fail'
    if fail_on_stale_temp_artifacts and temp_artifacts.get('stale_count'):
        status = 'fail'

    return {
        'doctor_failures': doctor_failures,
        'fail_on_future_report': fail_on_future_report,
        'fail_on_stale_lock': fail_on_stale_lock,
        'fail_on_stale_temp_artifacts': fail_on_stale_temp_artifacts,
        'fail_on_any_history_failure': fail_on_any_history_failure,
        'history': history_summary,
        'history_limit': history_limit,
        'max_report_age_minutes': max_report_age_minutes,
        'report_age_minutes': report_age_minutes,
        'report_future_seconds': report_future_seconds,
        'report_generated_at': report_generated_at,
        'report_matches_latest_history': report_history_match,
        'report_steps_complete': report_steps_complete,
        'report_status': report_status,
        'require_history_complete_steps': require_history_complete_steps,
        'require_history_current': require_history_current,
        'require_history_valid_timestamps': require_history_valid_timestamps,
        'require_report': require_report,
        'status': status,
        'temp_artifacts': temp_artifacts,
        'verification_lock': verification_lock,
    }


def calculate_report_age_minutes(generated_at: object, now: datetime | None = None) -> int | None:
    timestamp = parse_report_timestamp(generated_at)
    if timestamp is None:
        return None
    now = now or datetime.now(timezone.utc)
    return max(0, int((now - timestamp).total_seconds() // 60))


def calculate_report_future_seconds(generated_at: object, now: datetime | None = None) -> int | None:
    timestamp = parse_report_timestamp(generated_at)
    if timestamp is None:
        return None
    now = now or datetime.now(timezone.utc)
    return max(0, int((timestamp - now).total_seconds()))


def parse_report_timestamp(generated_at: object) -> datetime | None:
    if not isinstance(generated_at, str):
        return None
    try:
        timestamp = datetime.fromisoformat(generated_at)
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp


def format_status(status: dict[str, object]) -> str:
    lines = [
        '# GMGN Monitor Status',
        '',
        f"Status: {status['status']}",
        f"Report status: {status['report_status']}",
        f"Report generated at: {status['report_generated_at']}",
        f"Report age minutes: {status['report_age_minutes']}",
        f"Report future seconds: {status.get('report_future_seconds')}",
        f"Report matches latest history: {status['report_matches_latest_history']}",
        f"Report steps complete: {status['report_steps_complete']}",
    ]
    if status.get('max_report_age_minutes') is not None:
        lines.append(f"Max report age minutes: {status['max_report_age_minutes']}")
    if status.get('require_report'):
        lines.append(f"Require report: {status['require_report']}")
    if status.get('fail_on_future_report'):
        lines.append(f"Fail on future report: {status['fail_on_future_report']}")
    if status.get('require_history_complete_steps'):
        lines.append(f"Require history complete steps: {status['require_history_complete_steps']}")
    if status.get('require_history_valid_timestamps'):
        lines.append(f"Require history valid timestamps: {status['require_history_valid_timestamps']}")
    if status.get('require_history_current'):
        lines.append(f"Require history current: {status['require_history_current']}")
    lock = status.get('verification_lock')
    if isinstance(lock, dict):
        lines.extend([
            f"Verification lock present: {lock.get('exists')}",
            f"Verification lock stale: {lock.get('stale')}",
            f"Verification lock age seconds: {lock.get('age_seconds')}",
        ])
    if status.get('fail_on_stale_lock'):
        lines.append(f"Fail on stale lock: {status['fail_on_stale_lock']}")
    temp_artifacts = status.get('temp_artifacts')
    if isinstance(temp_artifacts, dict):
        lines.extend([
            f"Temp artifact count: {temp_artifacts.get('count')}",
            f"Stale temp artifact count: {temp_artifacts.get('stale_count')}",
        ])
    if status.get('fail_on_stale_temp_artifacts'):
        lines.append(f"Fail on stale temp artifacts: {status['fail_on_stale_temp_artifacts']}")
    history = status.get('history')
    if isinstance(history, dict):
        lines.extend([
            f"History limit: {status.get('history_limit')}",
            f"Fail on any history failure: {status.get('fail_on_any_history_failure')}",
            f"History records: {history.get('record_count')}",
            f"History failures: {history.get('failure_count')}",
            f"History incomplete step records: {history.get('incomplete_step_record_count')}",
            f"History status-step mismatch records: {history.get('status_step_mismatch_count')}",
            f"History invalid timestamp records: {history.get('invalid_timestamp_count')}",
            f"History future timestamp records: {history.get('future_timestamp_count')}",
            f"History out-of-order timestamp records: {history.get('out_of_order_timestamp_count')}",
            f"History last status: {history.get('last_status')}",
            f"History last record status matches steps: {history.get('last_record_status_matches_steps')}",
            f"History last record steps complete: {history.get('last_record_steps_complete')}",
            f"History last record timestamp valid: {history.get('last_record_timestamp_valid')}",
            f"History last record timestamp future: {history.get('last_record_timestamp_future')}",
        ])
    failures = status.get('doctor_failures')
    if isinstance(failures, list) and failures:
        lines.extend(['', '## Doctor Failures', ''])
        for failure in failures:
            lines.append(f'- {failure}')
    return '\n'.join(lines) + '\n'


def main() -> int:
    parser = argparse.ArgumentParser(description='Read local GMGN monitor status without running verification.')
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--history-limit', type=int, help='Read only the most recent N verification history records.')
    parser.add_argument('--fail-on-any-history-failure', action='store_true', help='Exit non-zero if any selected history record failed.')
    parser.add_argument('--require-history-complete-steps', action='store_true', help='Exit non-zero if any selected history record lacks the complete ok verification step set.')
    parser.add_argument('--require-history-valid-timestamps', action='store_true', help='Exit non-zero if any selected history record has an invalid, future, or out-of-order generated_at timestamp.')
    parser.add_argument('--max-report-age-minutes', type=int, help='Exit non-zero if the verification report is older than this.')
    parser.add_argument('--require-history-current', action='store_true', help='Exit non-zero unless the report matches the latest history record.')
    parser.add_argument('--require-report', action='store_true', help='Exit non-zero unless an ok verification report with a valid timestamp and complete ok step set exists.')
    parser.add_argument('--fail-on-future-report', action='store_true', help='Exit non-zero if the verification report timestamp is in the future.')
    parser.add_argument('--fail-on-stale-lock', action='store_true', help='Exit non-zero if data/verification.lock exists and is stale.')
    parser.add_argument('--fail-on-stale-temp-artifacts', action='store_true', help='Exit non-zero if stale atomic-write temp files exist under data/.')
    parser.add_argument('--json', action='store_true', help='Print machine-readable status output.')
    args = parser.parse_args()

    try:
        status = build_status(
            args.root,
            max_report_age_minutes=args.max_report_age_minutes,
            history_limit=args.history_limit,
            fail_on_any_history_failure=args.fail_on_any_history_failure,
            require_history_complete_steps=args.require_history_complete_steps,
            require_history_valid_timestamps=args.require_history_valid_timestamps,
            require_history_current=args.require_history_current,
            require_report=args.require_report,
            fail_on_future_report=args.fail_on_future_report,
            fail_on_stale_lock=args.fail_on_stale_lock,
            fail_on_stale_temp_artifacts=args.fail_on_stale_temp_artifacts,
        )
    except ValueError as exc:
        print(f'GMGN monitor status: {exc}')
        return 1
    if args.json:
        print(json.dumps(status, sort_keys=True))
    else:
        print(format_status(status), end='')
    return 0 if status['status'] == 'ok' else 1


if __name__ == '__main__':
    raise SystemExit(main())
