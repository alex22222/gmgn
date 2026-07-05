from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .doctor import run_checks, run_safety_scan
from .serialization import load_jsonl
from .file_io import LockAcquisitionError, atomic_write_text, durable_append_text, exclusive_file_lock
from .fingerprints import build_artifact_fingerprints, build_config_fingerprints
from .pipeline import run_pipeline
from .verification_expectations import check_operational_expectations, load_verification_expectations
from .verification_steps import report_has_required_steps


@dataclass(frozen=True)
class VerificationStep:
    name: str
    ok: bool
    details: list[str]


def run_verification(root: Path = Path('.')) -> list[VerificationStep]:
    root = root.resolve()
    steps: list[VerificationStep] = []
    steps.append(_run_pipeline_step(root))
    steps.append(_run_expectations_step(root))
    steps.append(_run_doctor_step(root))
    steps.append(_run_tests_step(root))
    steps.append(_run_safety_scan_step(root))
    return steps


def build_report(
    steps: list[VerificationStep],
    config_fingerprints: dict[str, str] | None = None,
    artifact_fingerprints: dict[str, str] | None = None,
    operational_summary: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        'artifact_fingerprints': artifact_fingerprints or {},
        'config_fingerprints': config_fingerprints or {},
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'operational_summary': operational_summary or {},
        'status': 'ok' if all(step.ok for step in steps) else 'fail',
        'steps': [
            {
                'name': step.name,
                'status': 'ok' if step.ok else 'fail',
                'details': step.details,
            }
            for step in steps
        ],
    }


def build_operational_summary(root: Path = Path('.')) -> dict[str, object]:
    root = root.resolve()
    events_path = root / 'data/pipeline/reviewed_candidate_events.jsonl'
    if not events_path.exists():
        events_path = root / 'data/pipeline/candidate_events.jsonl'

    decisions = {'alert': 0, 'watch': 0, 'reject': 0}
    reviewed = 0
    pending = 0
    candidate_count = 0
    if events_path.exists():
        for event in _load_operational_events(events_path):
            candidate_count += 1
            decision = event.get('decision')
            if decision in decisions:
                decisions[decision] += 1
            if event.get('outcome', {}).get('reviewed') is True:
                reviewed += 1
            else:
                pending += 1

    return {
        'automation_gate_status': _read_automation_gate_status(root),
        'candidate_count': candidate_count,
        'decisions': decisions,
        'outcomes': {
            'pending': pending,
            'reviewed': reviewed,
        },
    }


def _load_operational_events(path: Path) -> list[dict[str, object]]:
    return list(load_jsonl(path, label='operational summary events', object_label='event'))


def _read_automation_gate_status(root: Path) -> str | None:
    gate_path = root / 'data/pipeline/automation_gate.md'
    if not gate_path.exists():
        return None
    try:
        lines = gate_path.read_text(encoding='utf-8').splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError(f'{gate_path}: invalid operational summary gate UTF-8: {exc.reason}') from exc
    except OSError as exc:
        raise ValueError(f'{gate_path}: invalid operational summary gate read: {exc}') from exc
    for line in lines:
        if line.startswith('Status:'):
            return line.split(':', 1)[1].strip()
    return None


def write_report(report: dict[str, object], output_path: Path) -> None:
    atomic_write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', output_path)


def append_history(report: dict[str, object], output_path: Path) -> None:
    durable_append_text(json.dumps(report, sort_keys=True) + '\n', output_path)


def _run_pipeline_step(root: Path) -> VerificationStep:
    try:
        outputs = run_pipeline(
            input_path=root / 'fixtures/candidates.jsonl',
            output_dir=root / 'data/pipeline',
            threshold_config_path=root / 'config/thresholds.json',
            risk_config_path=root / 'config/risk_limits.json',
            automation_config_path=root / 'config/automation_gate.json',
            reviews_path=root / 'fixtures/outcome_reviews.jsonl',
            daily_loss_percent=0.0,
        )
    except Exception as exc:
        return VerificationStep('pipeline', False, [str(exc)])
    return VerificationStep('pipeline', True, [str(path.relative_to(root)) for path in outputs.values()])


def _run_expectations_step(root: Path) -> VerificationStep:
    path = root / 'config/verification_expectations.json'
    if not path.exists():
        return VerificationStep('expectations', False, [f'missing verification expectations: {path.relative_to(root)}'])
    try:
        failures = check_operational_expectations(
            build_operational_summary(root),
            load_verification_expectations(path),
        )
    except Exception as exc:
        return VerificationStep('expectations', False, [str(exc)])
    return VerificationStep('expectations', not failures, failures)


def _run_doctor_step(root: Path) -> VerificationStep:
    failures = run_checks(root, include_verification_artifacts=False)
    return VerificationStep('doctor', not failures, failures)


def _run_tests_step(root: Path) -> VerificationStep:
    completed = subprocess.run(
        [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests'],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    output = (completed.stdout + completed.stderr).strip()
    details = output.splitlines()[-8:] if output else []
    return VerificationStep('tests', completed.returncode == 0, details)


def _run_safety_scan_step(root: Path) -> VerificationStep:
    failures = run_safety_scan(root)
    return VerificationStep('safety_scan', not failures, failures)


def main() -> int:
    parser = argparse.ArgumentParser(description='Run the full local GMGN monitor verification chain.')
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--json', action='store_true', help='Print machine-readable verification output.')
    parser.add_argument('--report', type=Path, help='Write the verification report to a JSON file.')
    parser.add_argument('--history', type=Path, help='Append the verification report to a JSONL history file.')
    args = parser.parse_args()
    root = args.root.resolve()

    try:
        with exclusive_file_lock(root / 'data/verification.lock'):
            steps = run_verification(root)
            report = build_report(
                steps,
                build_config_fingerprints(root),
                build_artifact_fingerprints(root),
                build_operational_summary(root),
            )
            if args.report:
                report_path = args.report if args.report.is_absolute() else root / args.report
                write_report(report, report_path)
            if args.history:
                history_path = args.history if args.history.is_absolute() else root / args.history
                append_history(report, history_path)
    except LockAcquisitionError as exc:
        if args.json:
            print(json.dumps({'error': str(exc), 'status': 'fail'}, sort_keys=True))
        else:
            print(f'GMGN monitor verification: {exc}')
        return 1
    except (OSError, ValueError) as exc:
        if args.json:
            print(json.dumps({'error': str(exc), 'status': 'fail'}, sort_keys=True))
        else:
            print(f'GMGN monitor verification: {exc}')
        return 1

    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print(f"GMGN monitor verification: {str(report['status']).upper()}")
        if args.report:
            print(f"report: {report_path}")
        if args.history:
            print(f"history: {history_path}")
        for step in report['steps']:
            print(f"- {step['name']}: {step['status']}")
            if step['status'] != 'ok':
                for detail in step['details']:
                    print(f"  - {detail}")
    return 0 if report['status'] == 'ok' else 1


if __name__ == '__main__':
    raise SystemExit(main())
