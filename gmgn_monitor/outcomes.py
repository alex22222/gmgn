from __future__ import annotations

import argparse
from math import isfinite
from pathlib import Path

from .file_io import atomic_write_jsonl
from .serialization import load_jsonl
from .time_utils import is_iso_timestamp


OUTCOME_FIELDS = (
    'reviewed',
    'reviewed_at',
    'price_change_5m_percent',
    'price_change_30m_percent',
    'price_change_24h_percent',
    'max_drawdown_percent',
    'notes',
)


OUTCOME_NUMERIC_FIELDS = (
    'price_change_5m_percent',
    'price_change_30m_percent',
    'price_change_24h_percent',
    'max_drawdown_percent',
)


def load_reviews(path: Path) -> dict[str, dict]:
    reviews: dict[str, dict] = {}
    for review in load_jsonl(path):
        token_address = review.get('token_address')
        failures = _validate_review(review)
        if failures:
            raise ValueError('; '.join(failures))
        if token_address in reviews:
            raise ValueError(f'duplicate review token_address: {token_address}')
        reviews[token_address] = {field: review.get(field) for field in OUTCOME_FIELDS if field in review}
    return reviews


def _validate_review(review: dict) -> list[str]:
    failures: list[str] = []
    token_address = review.get('token_address')
    if not isinstance(token_address, str):
        failures.append('review missing token_address')
    elif not token_address.strip():
        failures.append('review token_address must be non-empty')
    if 'reviewed' in review and not isinstance(review['reviewed'], bool):
        failures.append('reviewed must be boolean')
    reviewed_at = review.get('reviewed_at')
    if reviewed_at is not None and (not isinstance(reviewed_at, str) or not is_iso_timestamp(reviewed_at)):
        failures.append('reviewed_at must be ISO timestamp or null')
    for field in OUTCOME_NUMERIC_FIELDS:
        value = review.get(field)
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value)):
            failures.append(f'{field} must be finite number or null')
    if 'notes' in review and not isinstance(review['notes'], str):
        failures.append('notes must be string')
    return failures


def apply_reviews(events: list[dict], reviews: dict[str, dict]) -> list[dict]:
    updated: list[dict] = []
    for event in events:
        token_reviews = reviews.get(event['token_address'])
        if not token_reviews:
            updated.append(event)
            continue
        outcome = {**event.get('outcome', {}), **token_reviews}
        updated.append({**event, 'outcome': outcome})
    return updated


def write_jsonl(records: list[dict], output_path: Path) -> None:
    atomic_write_jsonl(records, output_path)


def main() -> int:
    parser = argparse.ArgumentParser(description='Apply separate outcome reviews to scored monitor events.')
    parser.add_argument('--events', type=Path, default=Path('data/candidate_events.jsonl'))
    parser.add_argument('--reviews', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('data/reviewed_candidate_events.jsonl'))
    args = parser.parse_args()

    reviewed = apply_reviews(load_events(args.events), load_reviews(args.reviews))
    write_jsonl(reviewed, args.output)
    print(f'wrote {len(reviewed)} reviewed events to {args.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
