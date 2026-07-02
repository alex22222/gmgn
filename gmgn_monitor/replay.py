from __future__ import annotations

import argparse
from pathlib import Path

from .config import ThresholdConfig, load_threshold_config
from .file_io import atomic_write_jsonl
from .schema import Candidate
from .scoring import score_candidate
from .sources import CandidateSource, JsonlCandidateSource


def replay_source(source: CandidateSource, output_path: Path | None = None, threshold_config: ThresholdConfig | None = None) -> list[dict]:
    threshold_config = threshold_config or ThresholdConfig()
    results: list[dict] = []
    for raw in source.load():
        candidate = Candidate.from_dict(raw)
        thresholds = threshold_config.for_chain(candidate.get('chain'))
        results.append(_with_empty_outcome(score_candidate(candidate, thresholds)))

    if output_path:
        atomic_write_jsonl(results, output_path)

    return results


def replay(input_path: Path, output_path: Path | None = None, threshold_config: ThresholdConfig | None = None) -> list[dict]:
    return replay_source(JsonlCandidateSource(input_path), output_path, threshold_config)


def _with_empty_outcome(result: dict) -> dict:
    if 'outcome' in result:
        return result
    return {
        **result,
        'outcome': {
            'reviewed': False,
            'reviewed_at': None,
            'price_change_5m_percent': None,
            'price_change_30m_percent': None,
            'price_change_24h_percent': None,
            'max_drawdown_percent': None,
            'notes': '',
        },
    }


def print_summary(results: list[dict], details: bool = True) -> None:
    counts = {'reject': 0, 'watch': 0, 'alert': 0}
    for result in results:
        counts[result['decision']] += 1
        if details:
            reason_text = '; '.join(result['reasons'][:3])
            print(f"{result['decision'].upper():6} score={result['score']:3} {result['symbol']} {result['token_address']} - {reason_text}")

    print(f"summary: alert={counts['alert']} watch={counts['watch']} reject={counts['reject']}")


def main() -> int:
    parser = argparse.ArgumentParser(description='Replay monitor-only GMGN candidate fixtures.')
    parser.add_argument('--input', type=Path, default=Path('fixtures/candidates.jsonl'))
    parser.add_argument('--output', type=Path, default=Path('data/candidate_events.jsonl'))
    parser.add_argument('--config', type=Path, default=Path('config/thresholds.json'))
    parser.add_argument('--summary-only', action='store_true')
    args = parser.parse_args()

    threshold_config = load_threshold_config(args.config)
    results = replay(args.input, args.output, threshold_config)
    print_summary(results, details=not args.summary_only)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
