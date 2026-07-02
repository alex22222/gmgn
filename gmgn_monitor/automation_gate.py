from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .file_io import atomic_write_text
from .serialization import load_json


def evaluate_gate(config: dict) -> dict:
    blockers: list[str] = []

    if not config.get('positive_expectancy_after_costs'):
        blockers.append('positive expectancy after costs is not proven')
    if config.get('reviewed_candidate_count', 0) < config.get('minimum_reviewed_candidate_count', 200):
        blockers.append('reviewed candidate count is below minimum')
    if not config.get('paper_or_shadow_results_available'):
        blockers.append('paper or shadow results are not available')
    if not config.get('kill_switch_configured'):
        blockers.append('kill switch is not configured')
    if not config.get('mandatory_logs_configured'):
        blockers.append('mandatory logs are not configured')
    if not config.get('hard_daily_loss_limit_configured'):
        blockers.append('hard daily loss limit is not configured')
    if not config.get('security_review_completed'):
        blockers.append('security review is not completed')
    if config.get('allows_martingale'):
        blockers.append('martingale is not allowed')
    if config.get('allows_dca_into_losers'):
        blockers.append('DCA into losing meme tokens is not allowed')
    if config.get('allows_unlimited_retries'):
        blockers.append('unlimited retries are not allowed')

    return {
        'status': 'blocked' if blockers else 'eligible_for_tiny_size_testing',
        'blockers': blockers,
    }


def build_gate_report(config: dict) -> str:
    result = evaluate_gate(config)
    lines = [
        '# GMGN Automation Gate',
        '',
        f"Status: {result['status']}",
        '',
        'This gate does not execute trades or enable signing. It only evaluates whether limited automation may be considered.',
        '',
        '## Blockers',
        '',
    ]
    if result['blockers']:
        lines.extend(f"- {blocker}" for blocker in result['blockers'])
    else:
        lines.append('- none')
    return '\n'.join(lines) + '\n'


def load_config(path: Path) -> dict:
    config = load_json(path, label='automation gate config')
    if not isinstance(config, dict):
        raise ValueError('automation gate config must be an object')
    return config


def main() -> int:
    parser = argparse.ArgumentParser(description='Evaluate the Phase 5 automation gate without enabling trading.')
    parser.add_argument('--config', type=Path, default=Path('config/automation_gate.json'))
    parser.add_argument('--output', type=Path, default=Path('data/automation_gate.md'))
    args = parser.parse_args()

    try:
        report = build_gate_report(load_config(args.config))
    except ValueError as exc:
        print(f'invalid automation gate input: {exc}', file=sys.stderr)
        return 2
    try:
        atomic_write_text(report, args.output)
    except OSError as exc:
        print(f'failed to write automation gate report: {exc}', file=sys.stderr)
        return 2
    print(f'wrote automation gate report to {args.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
