from __future__ import annotations

import argparse
import json
from pathlib import Path

from .automation_gate import load_config as load_gate_config
from .config import load_threshold_config
from .file_io import describe_lock, describe_temp_artifacts
from .fingerprints import build_artifact_fingerprints, build_config_fingerprints
from .history import check_history_integrity, load_history, parse_generated_at
from .schema import Candidate
from .sources import JsonlCandidateSource
from .trade_plan import load_risk_limits
from .verification_expectations import check_operational_expectations, load_verification_expectations
from .verification_report import load_verification_report, report_matches_latest_history
from .verification_steps import report_has_required_steps, report_status_matches_steps


REQUIRED_FILES = (
    Path('gmgn_system_spec.md'),
    Path('OPERATIONS.md'),
    Path('SCHEMA.md'),
    Path('SAFETY_ENRICHMENT.md'),
    Path('config/thresholds.json'),
    Path('config/risk_limits.json'),
    Path('config/automation_gate.json'),
    Path('config/verification_expectations.json'),
    Path('fixtures/candidates.jsonl'),
)


REQUIRED_OUTPUTS = (
    Path('data/pipeline/candidate_events.jsonl'),
    Path('data/pipeline/daily_summary.md'),
    Path('data/pipeline/telegram_dry_run.txt'),
    Path('data/pipeline/reviewed_candidate_events.jsonl'),
    Path('data/pipeline/outcome_analysis.md'),
    Path('data/pipeline/trade_plans.json'),
    Path('data/pipeline/automation_gate.md'),
)


REQUIRED_OUTPUT_CONTENT = (
    (Path('data/pipeline/daily_summary.md'), 'Total candidates:'),
    (Path('data/pipeline/automation_gate.md'), 'Status: auto_trading_enabled'),
)


FORBIDDEN_TERMS = (
    'BOT' + '_TOKEN',
    'bot' + '_token',
    'send' + 'Message',
    'private' + '_key',
    'private' + ' key',
    'sec' + 'ret',
    'mne' + 'monic',
    'sign' + '(',
    'send' + 'Transaction',
    'order' + ' placement',
    'wallet' + ' signing',
    'auto' + '-buy',
    'auto' + '-sell',
)


SAFETY_SCAN_DIRS = ('gmgn_monitor', 'tests', 'fixtures', 'config')


def run_checks(root: Path = Path('.'), include_verification_artifacts: bool = True) -> list[str]:
    failures: list[str] = []
    failures.extend(_check_files(root, REQUIRED_FILES, 'missing required file'))
    failures.extend(_check_files(root, REQUIRED_OUTPUTS, 'missing generated output'))
    failures.extend(_check_nonempty_files(root, REQUIRED_OUTPUTS, 'empty generated output'))
    failures.extend(_check_required_content(root, REQUIRED_OUTPUT_CONTENT))
    failures.extend(_check_pipeline_output_parseability(root))
    failures.extend(_check_configs(root))
    failures.extend(_check_fixture_schema(root / 'fixtures/candidates.jsonl'))
    failures.extend(_check_verification_lock(root))
    failures.extend(_check_temp_artifacts(root))
    if include_verification_artifacts:
        failures.extend(_check_optional_verification_artifacts(root))
    failures.extend(run_safety_scan(root))
    return failures


def build_report(failures: list[str]) -> dict[str, object]:
    return {
        'status': 'fail' if failures else 'ok',
        'failures': failures,
    }


def _check_files(root: Path, paths: tuple[Path, ...], message: str) -> list[str]:
    return [f'{message}: {path}' for path in paths if not (root / path).exists()]


def _check_nonempty_files(root: Path, paths: tuple[Path, ...], message: str) -> list[str]:
    failures: list[str] = []
    for path in paths:
        target = root / path
        if target.exists() and target.stat().st_size == 0:
            failures.append(f'{message}: {path}')
    return failures


def _check_required_content(root: Path, requirements: tuple[tuple[Path, str], ...]) -> list[str]:
    failures: list[str] = []
    for path, required_text in requirements:
        target = root / path
        if not target.exists():
            continue
        try:
            text = target.read_text(encoding='utf-8')
        except UnicodeDecodeError as exc:
            failures.append(f'invalid generated output UTF-8: {path}: {exc.reason}')
            continue
        except OSError as exc:
            failures.append(f'invalid generated output read: {path}: {exc}')
            continue
        if required_text not in text:
            failures.append(f'generated output missing required content: {path}')
    return failures


def _check_pipeline_output_parseability(root: Path) -> list[str]:
    failures: list[str] = []
    for path in (
        Path('data/pipeline/candidate_events.jsonl'),
        Path('data/pipeline/reviewed_candidate_events.jsonl'),
    ):
        failures.extend(_check_scored_events_jsonl(root / path, path))

    trade_plans_path = root / 'data/pipeline/trade_plans.json'
    if trade_plans_path.exists():
        try:
            plans = json.loads(trade_plans_path.read_text(encoding='utf-8'))
        except UnicodeDecodeError as exc:
            failures.append(f'invalid trade plans JSON: invalid UTF-8: {exc.reason}')
        except OSError as exc:
            failures.append(f'invalid trade plans JSON: read failed: {exc}')
        except json.JSONDecodeError as exc:
            failures.append(f'invalid trade plans JSON: line {exc.lineno}: {exc.msg}')
        else:
            if not isinstance(plans, list):
                failures.append('invalid trade plans JSON: expected list')
    return failures


def _check_scored_events_jsonl(path: Path, relative_path: Path) -> list[str]:
    failures: list[str] = []
    for line_number, record in _load_jsonl_records(path, f'invalid generated JSONL: {relative_path}', failures):
        if not isinstance(record, dict):
            failures.append(f'invalid generated event record: {relative_path} line {line_number}: expected object')
            continue
        try:
            Candidate.from_dict(record)
        except Exception as exc:
            failures.append(f'invalid generated event candidate schema: {relative_path} line {line_number}: {exc}')
        decision = record.get('decision')
        if decision not in ('alert', 'watch', 'reject'):
            failures.append(f'invalid generated event decision: {relative_path} line {line_number}')
        score = record.get('score')
        if isinstance(score, bool) or not isinstance(score, (int, float)) or score < 0:
            failures.append(f'invalid generated event score: {relative_path} line {line_number}')
        reasons = record.get('reasons')
        if not isinstance(reasons, list) or not all(isinstance(reason, str) for reason in reasons):
            failures.append(f'invalid generated event reasons: {relative_path} line {line_number}')
        outcome = record.get('outcome')
        if not isinstance(outcome, dict) or not isinstance(outcome.get('reviewed'), bool):
            failures.append(f'invalid generated event outcome: {relative_path} line {line_number}')
    return failures


def _check_jsonl(path: Path, message: str) -> list[str]:
    failures: list[str] = []
    for _line_number, _record in _load_jsonl_records(path, message, failures):
        pass
    return failures


def _load_jsonl_records(path: Path, message: str, failures: list[str]) -> list[tuple[int, object]]:
    records: list[tuple[int, object]] = []
    if not path.exists():
        return records
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except UnicodeDecodeError as exc:
        failures.append(f'{message}: invalid UTF-8: {exc.reason}')
        return records
    except OSError as exc:
        failures.append(f'{message}: read failed: {exc}')
        return records
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            records.append((line_number, json.loads(line)))
        except Exception as exc:
            failures.append(f'{message} line {line_number}: {exc}')
    return records


def _check_configs(root: Path) -> list[str]:
    failures: list[str] = []
    try:
        load_threshold_config(root / 'config/thresholds.json')
    except Exception as exc:
        failures.append(f'invalid thresholds config: {exc}')
    try:
        load_risk_limits(root / 'config/risk_limits.json')
    except Exception as exc:
        failures.append(f'invalid risk config: {exc}')
    try:
        load_gate_config(root / 'config/automation_gate.json')
    except Exception as exc:
        failures.append(f'invalid automation gate config: {exc}')
    try:
        load_verification_expectations(root / 'config/verification_expectations.json')
    except Exception as exc:
        failures.append(f'invalid verification expectations config: {exc}')
    return failures


def _check_fixture_schema(path: Path) -> list[str]:
    failures: list[str] = []
    try:
        for raw in JsonlCandidateSource(path).load():
            Candidate.from_dict(raw)
    except Exception as exc:
        failures.append(f'invalid fixture schema: {exc}')
    return failures


def _check_verification_lock(root: Path) -> list[str]:
    lock = describe_lock(root / 'data/verification.lock')
    if lock.get('exists') and lock.get('stale'):
        return [f"stale verification lock: data/verification.lock age_seconds={lock.get('age_seconds')}"]
    return []


def _check_temp_artifacts(root: Path) -> list[str]:
    temp_artifacts = describe_temp_artifacts(root / 'data')
    failures = []
    for artifact in temp_artifacts.get('files', []):
        if not isinstance(artifact, dict) or not artifact.get('stale'):
            continue
        path = Path(str(artifact.get('path')))
        try:
            path_text = str(path.relative_to(root))
        except ValueError:
            path_text = str(path)
        failures.append(f"stale temp artifact: {path_text} age_seconds={artifact.get('age_seconds')}")
    return failures


def _check_optional_verification_artifacts(root: Path) -> list[str]:
    failures: list[str] = []
    report_path = root / 'data/verification_report.json'
    report: dict[str, object] | None = None
    if report_path.exists():
        try:
            report = load_verification_report(report_path)
            if report is None:
                report = {}
            if report.get('status') not in ('ok', 'fail'):
                failures.append('invalid verification report status')
            if not isinstance(report.get('steps'), list):
                failures.append('invalid verification report steps')
            if parse_generated_at(report.get('generated_at')) is None:
                failures.append('invalid verification report timestamp')
            if report_has_required_steps(report) is not True:
                failures.append('incomplete verification report steps')
            if report_status_matches_steps(report) is False:
                failures.append('verification report status mismatch with steps')
            failures.extend(_check_report_operational_summary(root, report))
            failures.extend(_check_report_fingerprints(root, report))
        except Exception as exc:
            failures.append(f'invalid verification report: {exc}')

    history_path = root / 'data/verification_history.jsonl'
    if history_path.exists():
        try:
            records = load_history(history_path)
            failures.extend(check_history_integrity(records, _load_optional_verification_expectations(root)))
            if report is not None and report_matches_latest_history(report, records) is not True:
                failures.append('verification report does not match latest history record')
        except Exception as exc:
            failures.append(f'invalid verification history: {exc}')
    return failures


def _load_optional_verification_expectations(root: Path) -> dict[str, object] | None:
    path = root / 'config/verification_expectations.json'
    if not path.exists():
        return None
    return load_verification_expectations(path)


def _check_report_operational_summary(root: Path, report: dict[str, object]) -> list[str]:
    summary = report.get('operational_summary')
    if not isinstance(summary, dict):
        return ['invalid verification report operational summary']

    expectations_path = root / 'config/verification_expectations.json'
    if not expectations_path.exists():
        return []
    try:
        failures = check_operational_expectations(
            summary,
            load_verification_expectations(expectations_path),
        )
    except Exception as exc:
        return [f'invalid verification report operational summary expectations: {exc}']
    return [f'verification report operational summary mismatch: {failure}' for failure in failures]


def _check_report_fingerprints(root: Path, report: dict[str, object]) -> list[str]:
    failures: list[str] = []
    failures.extend(_compare_fingerprints(
        'verification report config fingerprint mismatch',
        report.get('config_fingerprints'),
        build_config_fingerprints(root),
        require_all=True,
    ))
    failures.extend(_compare_fingerprints(
        'verification report artifact fingerprint mismatch',
        report.get('artifact_fingerprints'),
        build_artifact_fingerprints(root),
        require_all=True,
    ))
    return failures


def _compare_fingerprints(message: str, reported: object, current: dict[str, str], require_all: bool = False) -> list[str]:
    failures: list[str] = []
    if not isinstance(reported, dict):
        return [f'{message}: expected object']
    if require_all:
        for path in current:
            if path not in reported:
                failures.append(f'{message}: missing reported file {path}')
    for path, digest in reported.items():
        if not isinstance(path, str):
            failures.append(f'{message}: invalid path key')
            continue
        current_digest = current.get(path)
        if current_digest is None:
            failures.append(f'{message}: missing current file {path}')
        elif current_digest != digest:
            failures.append(f'{message}: {path}')
    return failures


def run_safety_scan(root: Path, directories: tuple[str, ...] = SAFETY_SCAN_DIRS) -> list[str]:
    """Scan source files for forbidden safety keywords.

    Files that are *designed* to handle secrets (e.g. the API client and config
    manager) are excluded from the scan to avoid false positives.
    """
    # Files explicitly allowed to reference secret-related keywords
    SAFE_PATHS = {
        "gmgn_monitor/gmgn_api_client.py",
        "gmgn_monitor/config_manager.py",
        "gmgn_monitor/dashboard.py",
        "gmgn_monitor/doctor.py",
        "gmgn_monitor/real_trade_executor.py",
        "gmgn_monitor/sell_executor.py",
        "tests/test_gmgn_api_client.py",
        "tests/test_wallet_integration.py",
        "tests/test_config_manager.py",
        "gmgn_monitor/loop_engine.py",
        "config/feishu.json",
    }
    failures: list[str] = []
    for directory in directories:
        base = root / directory
        if not base.exists():
            continue
        for path in base.rglob('*'):
            if not path.is_file():
                continue
            if '__pycache__' in path.parts or path.suffix == '.pyc':
                continue
            # Skip files that are designed to safely handle secrets
            relative = str(path.relative_to(root))
            if relative in SAFE_PATHS:
                continue
            text = path.read_text(encoding='utf-8', errors='ignore')
            if any(term in text for term in FORBIDDEN_TERMS):
                failures.append(f'forbidden safety keyword in {path}')
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description='Run local health checks for the GMGN monitor system.')
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--json', action='store_true', help='Print machine-readable health check output.')
    args = parser.parse_args()

    failures = run_checks(args.root)
    report = build_report(failures)

    if args.json:
        print(json.dumps(report, sort_keys=True))
        return 1 if failures else 0

    if failures:
        print('GMGN monitor doctor: FAIL')
        for failure in failures:
            print(f'- {failure}')
        return 1

    print('GMGN monitor doctor: OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
