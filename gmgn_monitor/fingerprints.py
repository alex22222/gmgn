from __future__ import annotations

import hashlib
from pathlib import Path


CONFIG_FILES = (
    Path('config/thresholds.json'),
    Path('config/risk_limits.json'),
    Path('config/automation_gate.json'),
    Path('config/execution_venues.json'),
    Path('config/verification_expectations.json'),
)


ARTIFACT_FILES = (
    Path('data/pipeline/candidate_events.jsonl'),
    Path('data/pipeline/daily_summary.md'),
    Path('data/pipeline/telegram_dry_run.txt'),
    Path('data/pipeline/reviewed_candidate_events.jsonl'),
    Path('data/pipeline/outcome_analysis.md'),
    Path('data/pipeline/trade_plans.json'),
    Path('data/pipeline/automation_gate.md'),
)


def build_config_fingerprints(root: Path = Path('.')) -> dict[str, str]:
    return build_fingerprints(root, CONFIG_FILES)


def build_artifact_fingerprints(root: Path = Path('.')) -> dict[str, str]:
    return build_fingerprints(root, ARTIFACT_FILES)


def build_fingerprints(root: Path, paths: tuple[Path, ...]) -> dict[str, str]:
    root = root.resolve()
    fingerprints: dict[str, str] = {}
    for path in paths:
        target = root / path
        if target.exists():
            try:
                content = target.read_bytes()
            except OSError as exc:
                raise ValueError(f'invalid fingerprint input: {path}: {exc}') from exc
            fingerprints[str(path)] = hashlib.sha256(content).hexdigest()
    return fingerprints
