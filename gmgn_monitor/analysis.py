from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

from .file_io import atomic_write_text
from .sources import load_events


PRICE_FIELDS = (
    'price_change_5m_percent',
    'price_change_30m_percent',
    'price_change_24h_percent',
    'max_drawdown_percent',
)


def build_analysis_report(events: list[dict]) -> str:
    score_buckets = Counter(_score_bucket(event['score']) for event in events)
    reviewed = [event for event in events if event.get('outcome', {}).get('reviewed')]
    reviewed_by_decision = defaultdict(list)
    for event in reviewed:
        reviewed_by_decision[event['decision']].append(event)

    lines = [
        '# GMGN Monitor Score And Outcome Analysis',
        '',
        f'Total candidates: {len(events)}',
        f'Reviewed candidates: {len(reviewed)}',
        '',
        '## Score Buckets',
        '',
        _format_counts(score_buckets, ('0-24', '25-49', '50-74', '75-100')),
        '',
        '## Reviewed Outcomes By Decision',
        '',
        _format_reviewed(reviewed_by_decision),
    ]

    return '\n'.join(lines) + '\n'


def _score_bucket(score: int) -> str:
    if score < 25:
        return '0-24'
    if score < 50:
        return '25-49'
    if score < 75:
        return '50-74'
    return '75-100'


def _format_counts(counts: Counter, keys) -> str:
    rows = ['| Bucket | Count |', '|---|---:|']
    for key in keys:
        rows.append(f'| {key} | {counts.get(key, 0)} |')
    return '\n'.join(rows)


def _format_reviewed(reviewed_by_decision: dict[str, list[dict]]) -> str:
    rows = ['| Decision | Reviewed | Avg 5m | Avg 30m | Avg 24h | Avg Drawdown |', '|---|---:|---:|---:|---:|---:|']
    for decision in ('alert', 'watch', 'reject'):
        events = reviewed_by_decision.get(decision, [])
        rows.append(
            f"| {decision} | {len(events)} | "
            f"{_average(events, 'price_change_5m_percent')} | "
            f"{_average(events, 'price_change_30m_percent')} | "
            f"{_average(events, 'price_change_24h_percent')} | "
            f"{_average(events, 'max_drawdown_percent')} |"
        )
    return '\n'.join(rows)


def _average(events: list[dict], field: str) -> str:
    values = [
        event.get('outcome', {}).get(field)
        for event in events
        if isinstance(event.get('outcome', {}).get(field), (int, float))
    ]
    if not values:
        return 'n/a'
    return f'{sum(values) / len(values):.2f}'


def main() -> int:
    parser = argparse.ArgumentParser(description='Analyze score distribution and reviewed outcomes.')
    parser.add_argument('--input', type=Path, default=Path('data/reviewed_candidate_events.jsonl'))
    parser.add_argument('--output', type=Path, default=Path('data/outcome_analysis.md'))
    args = parser.parse_args()

    try:
        report = build_analysis_report(load_events(args.input))
    except ValueError as exc:
        print(f'invalid analysis input: {exc}', file=sys.stderr)
        return 2
    try:
        atomic_write_text(report, args.output)
    except OSError as exc:
        print(f'failed to write analysis report: {exc}', file=sys.stderr)
        return 2
    print(f'wrote outcome analysis to {args.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
