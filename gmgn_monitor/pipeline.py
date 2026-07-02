from __future__ import annotations

import argparse
from pathlib import Path

from .analysis import build_analysis_report
from .automation_gate import build_gate_report, load_config as load_gate_config
from .config import load_threshold_config
from .file_io import atomic_write_text
from .outcomes import apply_reviews, load_reviews, write_jsonl as write_events_jsonl
from .replay import replay
from .report import build_markdown_report
from .sources import JsonlCandidateSource
from .telegram_dry_run import build_messages
from .trade_plan import build_trade_plans, load_risk_limits, write_json


def run_pipeline(
    input_path: Path,
    output_dir: Path,
    threshold_config_path: Path,
    risk_config_path: Path,
    automation_config_path: Path,
    reviews_path: Path | None = None,
    daily_loss_percent: float = 0.0,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    threshold_config = load_threshold_config(threshold_config_path)

    events_path = output_dir / 'candidate_events.jsonl'
    events = replay(input_path, events_path, threshold_config)

    telegram_path = output_dir / 'telegram_dry_run.txt'
    atomic_write_text('\n\n---\n\n'.join(build_messages(events)) + '\n', telegram_path)

    reviewed_events = events
    reviewed_path = output_dir / 'reviewed_candidate_events.jsonl'
    if reviews_path:
        reviewed_events = apply_reviews(events, load_reviews(reviews_path))
    write_events_jsonl(reviewed_events, reviewed_path)

    summary_path = output_dir / 'daily_summary.md'
    atomic_write_text(build_markdown_report(reviewed_events), summary_path)

    analysis_path = output_dir / 'outcome_analysis.md'
    atomic_write_text(build_analysis_report(reviewed_events), analysis_path)

    plans_path = output_dir / 'trade_plans.json'
    plans = build_trade_plans(events, load_risk_limits(risk_config_path), daily_loss_percent)
    write_json(plans, plans_path)

    gate_path = output_dir / 'automation_gate.md'
    atomic_write_text(build_gate_report(load_gate_config(automation_config_path)), gate_path)

    return {
        'events': events_path,
        'summary': summary_path,
        'telegram': telegram_path,
        'reviewed_events': reviewed_path,
        'analysis': analysis_path,
        'trade_plans': plans_path,
        'automation_gate': gate_path,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='Run the local GMGN monitor dry-run pipeline.')
    parser.add_argument('--input', type=Path, default=Path('fixtures/candidates.jsonl'))
    parser.add_argument('--output-dir', type=Path, default=Path('data/pipeline'))
    parser.add_argument('--threshold-config', type=Path, default=Path('config/thresholds.json'))
    parser.add_argument('--risk-config', type=Path, default=Path('config/risk_limits.json'))
    parser.add_argument('--automation-config', type=Path, default=Path('config/automation_gate.json'))
    parser.add_argument('--reviews', type=Path)
    parser.add_argument('--daily-loss-percent', type=float, default=0.0)
    args = parser.parse_args()

    outputs = run_pipeline(
        input_path=args.input,
        output_dir=args.output_dir,
        threshold_config_path=args.threshold_config,
        risk_config_path=args.risk_config,
        automation_config_path=args.automation_config,
        reviews_path=args.reviews,
        daily_loss_percent=args.daily_loss_percent,
    )
    for name, path in outputs.items():
        print(f'{name}: {path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
