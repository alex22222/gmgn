from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .file_io import atomic_write_text
from .serialization import load_json


CUSTODY_RISK_ORDER = {
    'external_execution_surface': 1,
    'bot_wallet_surface': 2,
    'self_custody_engineering_risk': 3,
}


RELIABILITY_ORDER = {
    'measured': 0,
    'needs_live_measurement': 1,
    'not_implemented': 2,
}

REQUIRED_VENUE_FIELDS = (
    'name',
    'role',
    'estimated_fee_percent',
    'latency_tier',
    'custody_risk',
    'reliability_status',
    'notes',
)


def load_venues(path: Path) -> list[dict]:
    venues = load_json(path, label='execution venues')
    _validate_venues(venues)
    return venues


def _validate_venues(venues: object) -> None:
    if not isinstance(venues, list):
        raise ValueError('execution venues config must be a list')
    for index, venue in enumerate(venues, start=1):
        if not isinstance(venue, dict):
            raise ValueError(f'execution venue {index} must be an object')
        for field in REQUIRED_VENUE_FIELDS:
            if field not in venue:
                raise ValueError(f'execution venue {index} missing field: {field}')


def rank_venues(venues: list[dict]) -> list[dict]:
    return sorted(
        venues,
        key=lambda venue: (
            RELIABILITY_ORDER.get(venue['reliability_status'], 99),
            venue['estimated_fee_percent'],
            CUSTODY_RISK_ORDER.get(venue['custody_risk'], 99),
            venue['name'],
        ),
    )


def build_execution_report(venues: list[dict]) -> str:
    ranked = rank_venues(venues)
    lines = [
        '# GMGN Execution Layer Evaluation',
        '',
        'This report is evaluation-only. It does not integrate with wallets, signing, or trading APIs.',
        '',
        '## Ranked Venues',
        '',
        '| Rank | Venue | Role | Fee % | Latency | Custody Risk | Measurement |',
        '|---:|---|---|---:|---|---|---|',
    ]

    for index, venue in enumerate(ranked, start=1):
        lines.append(
            f"| {index} | {venue['name']} | {venue['role']} | {venue['estimated_fee_percent']} | "
            f"{venue['latency_tier']} | {venue['custody_risk']} | {venue['reliability_status']} |"
        )

    lines.extend([
        '',
        '## Notes',
        '',
    ])
    for venue in ranked:
        lines.append(f"- {venue['name']}: {venue['notes']}")

    lines.extend([
        '',
        '## Phase 4 Gate',
        '',
        'No venue should be selected for real execution until fill quality, failed transaction rate, slippage, fee cost, and custody risk are measured with non-trading or paper workflows. Not-implemented venues must remain below measured or measurement-ready venues regardless of nominal fee.',
    ])

    return '\n'.join(lines) + '\n'


def main() -> int:
    parser = argparse.ArgumentParser(description='Build a dry-run execution venue evaluation report.')
    parser.add_argument('--input', type=Path, default=Path('config/execution_venues.json'))
    parser.add_argument('--output', type=Path, default=Path('data/execution_evaluation.md'))
    args = parser.parse_args()

    try:
        report = build_execution_report(load_venues(args.input))
    except ValueError as exc:
        print(f'invalid execution evaluation input: {exc}', file=sys.stderr)
        return 2
    try:
        atomic_write_text(report, args.output)
    except OSError as exc:
        print(f'failed to write execution evaluation: {exc}', file=sys.stderr)
        return 2
    print(f'wrote execution evaluation to {args.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
