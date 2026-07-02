from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .file_io import atomic_write_jsonl


def build_candidate(index: int) -> dict:
    chain = ('solana', 'base', 'bsc')[index % 3]
    profile = index % 5
    base = {
        'chain': chain,
        'token_address': f'Sample{index:036d}',
        'symbol': f'SMP{index:03d}',
        'detected_at': f'2026-07-01T16:{index % 60:02d}:00Z',
        'source': 'fixture:large_sample',
        'liquidity': 140.0,
        'market_cap': 69000.0 + index,
        'volume_1m': 220.0,
        'volume_5m': 1800.0,
        'tx_count_1m': 85,
        'holder_count': 280,
        'top10_holder_percent': 18.0,
        'dev_holding_percent': 1.2,
        'insider_or_rat_percent': 6.0,
        'bundle_buy_percent': 4.0,
        'mint_renounced': True,
        'freeze_renounced': True,
        'lp_burned_or_locked': True,
        'honeypot_risk': False,
        'blacklist_risk': False,
        'tax_risk': False,
    }

    if profile == 1:
        base.update({
            'holder_count': 110,
            'top10_holder_percent': 24.0,
            'dev_holding_percent': 3.8,
            'insider_or_rat_percent': 14.0,
            'bundle_buy_percent': 18.0,
        })
    elif profile == 2:
        base.update({
            'top10_holder_percent': 44.0,
            'dev_holding_percent': 9.5,
            'insider_or_rat_percent': 24.0,
        })
    elif profile == 3:
        base.update({
            'honeypot_risk': True,
            'lp_burned_or_locked': False,
        })
    elif profile == 4:
        base.update({
            'liquidity': 20.0,
            'volume_5m': 80.0,
            'tx_count_1m': 5,
            'holder_count': 20,
            'bundle_buy_percent': 35.0,
        })

    return base


def generate_candidates(count: int) -> list[dict]:
    if count < 0:
        raise ValueError('sample candidate count must be non-negative')
    return [build_candidate(index) for index in range(count)]


def write_jsonl(records: list[dict], output_path: Path) -> None:
    atomic_write_jsonl(records, output_path)


def main() -> int:
    parser = argparse.ArgumentParser(description='Generate deterministic monitor-only sample candidates.')
    parser.add_argument('--count', type=int, default=200)
    parser.add_argument('--output', type=Path, default=Path('fixtures/large_sample_candidates.jsonl'))
    args = parser.parse_args()

    try:
        records = generate_candidates(args.count)
    except ValueError as exc:
        print(f'invalid sample-data input: {exc}', file=sys.stderr)
        return 2
    try:
        write_jsonl(records, args.output)
    except OSError as exc:
        print(f'failed to write sample candidates: {exc}', file=sys.stderr)
        return 2
    print(f'wrote {args.count} sample candidates to {args.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
