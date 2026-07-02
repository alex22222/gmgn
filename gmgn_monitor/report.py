from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from .file_io import atomic_write_text
from .sources import load_events


def build_markdown_report(events: list[dict], title: str = 'GMGN Monitor Daily Summary') -> str:
    decision_counts = Counter(event['decision'] for event in events)
    chain_counts = Counter(event['chain'] for event in events)
    source_counts = Counter(event['source'] for event in events)
    outcome_counts = Counter('reviewed' if event.get('outcome', {}).get('reviewed') else 'pending' for event in events)
    notable = [
        event
        for event in sorted(events, key=lambda item: item['score'], reverse=True)
        if event['decision'] in ('alert', 'watch')
    ][:10]

    lines = [
        f'# {title}',
        '',
        f'Total candidates: {len(events)}',
        '',
        '## Decisions',
        '',
        _format_counts(decision_counts, ('alert', 'watch', 'reject')),
        '',
        '## Chains',
        '',
        _format_counts(chain_counts, sorted(chain_counts)),
        '',
        '## Sources',
        '',
        _format_counts(source_counts, sorted(source_counts)),
        '',
        '## Outcome Review',
        '',
        _format_counts(outcome_counts, ('reviewed', 'pending')),
        '',
        '## Top Alert/Watch Candidates',
        '',
    ]

    if notable:
        lines.extend(_format_notable(notable))
    else:
        lines.append('No alert or watch candidates.')

    return '\n'.join(lines) + '\n'


def _format_counts(counts: Counter, keys) -> str:
    rows = ['| Key | Count |', '|---|---:|']
    for key in keys:
        rows.append(f'| {key} | {counts.get(key, 0)} |')
    return '\n'.join(rows)


def _format_notable(events: list[dict]) -> list[str]:
    rows = ['| Decision | Score | Chain | Symbol | Reason |', '|---|---:|---|---|---|']
    for event in events:
        reason = '; '.join(event.get('reasons', [])[:2])
        rows.append(f"| {event['decision']} | {event['score']} | {event['chain']} | {event['symbol']} | {reason} |")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description='Build a markdown summary from monitor-only candidate events.')
    parser.add_argument('--input', type=Path, default=Path('data/candidate_events.jsonl'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--title', default='GMGN Monitor Daily Summary')
    args = parser.parse_args()

    try:
        report = build_markdown_report(load_events(args.input), title=args.title)
    except ValueError as exc:
        print(f'invalid report input: {exc}', file=sys.stderr)
        return 2
    if args.output:
        try:
            atomic_write_text(report, args.output)
        except OSError as exc:
            print(f'failed to write report: {exc}', file=sys.stderr)
            return 2
    else:
        print(report, end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
