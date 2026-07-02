from __future__ import annotations

import argparse
from math import isfinite
from pathlib import Path

from .file_io import atomic_write_json
from .serialization import load_json
from .sources import load_events


REQUIRED_RISK_LIMIT_FIELDS = (
    'daily_loss_limit_percent',
    'max_single_position_percent',
    'default_stop_loss_percent',
    'take_profit_steps',
)


def load_risk_limits(path: Path) -> dict:
    raw = load_json(path, label='risk limits')
    _validate_risk_limits(raw)
    return raw


def build_trade_plans(events: list[dict], risk_limits: dict, daily_loss_percent: float = 0.0) -> list[dict]:
    if daily_loss_percent >= risk_limits['daily_loss_limit_percent']:
        return [{
            'status': 'blocked',
            'reason': 'daily loss limit reached',
            'daily_loss_percent': daily_loss_percent,
            'daily_loss_limit_percent': risk_limits['daily_loss_limit_percent'],
        }]

    plans: list[dict] = []
    for event in events:
        if event['decision'] not in ('alert', 'watch'):
            continue
        plans.append(_build_plan(event, risk_limits))
    return plans


def write_json(records: list[dict], output_path: Path) -> None:
    atomic_write_json(records, output_path)


def _build_plan(event: dict, risk_limits: dict) -> dict:
    return {
        'status': 'needs_human_confirmation',
        'symbol': event['symbol'],
        'chain': event['chain'],
        'token_address': event['token_address'],
        'decision': event['decision'],
        'score': event['score'],
        'max_position_percent': risk_limits['max_single_position_percent'],
        'reason': '; '.join(event.get('reasons', [])[:4]),
        'invalidation_rule': 'Do not enter if any safety flag changes, liquidity drops sharply, or concentration exceeds configured thresholds.',
        'exit_plan': {
            'stop_loss_percent': risk_limits['default_stop_loss_percent'],
            'take_profit_steps': risk_limits['take_profit_steps'],
        },
        'manual_checklist': [
            'Confirm token address matches the reviewed candidate.',
            'Confirm safety fields are still valid.',
            'Confirm daily loss limit has not been reached.',
            'Confirm position size is within max_position_percent.',
            'Confirm stop loss and take-profit plan before any manual action.',
        ],
    }


def _validate_risk_limits(raw: dict) -> None:
    if not isinstance(raw, dict):
        raise ValueError('risk limits config must be an object')

    for field in REQUIRED_RISK_LIMIT_FIELDS:
        if field not in raw:
            raise ValueError(f'missing risk limit field: {field}')

    allowed = set(REQUIRED_RISK_LIMIT_FIELDS)
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f'unknown risk limit fields: {", ".join(unknown)}')

    _require_number(raw, 'daily_loss_limit_percent')
    _require_number(raw, 'max_single_position_percent')
    _require_number(raw, 'default_stop_loss_percent')

    if raw['daily_loss_limit_percent'] <= 0:
        raise ValueError('daily_loss_limit_percent must be greater than 0')
    if raw['max_single_position_percent'] <= 0:
        raise ValueError('max_single_position_percent must be greater than 0')
    if raw['default_stop_loss_percent'] >= 0:
        raise ValueError('default_stop_loss_percent must be negative')

    steps = raw['take_profit_steps']
    if not isinstance(steps, list) or not steps:
        raise ValueError('take_profit_steps must be a non-empty list')

    total_sell_percent = 0.0
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise ValueError(f'take_profit_steps[{index}] must be an object')
        for field in ('price_change_percent', 'sell_percent'):
            if field not in step:
                raise ValueError(f'take_profit_steps[{index}] missing field: {field}')
            _require_number(step, field, f'take_profit_steps[{index}].{field}')
            if step[field] <= 0:
                raise ValueError(f'take_profit_steps[{index}].{field} must be greater than 0')
        total_sell_percent += step['sell_percent']

    if abs(total_sell_percent - 100.0) > 0.000001:
        raise ValueError('take_profit_steps sell_percent values must sum to 100')


def _require_number(data: dict, field: str, label: str | None = None) -> None:
    value = data[field]
    label = label or field
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{label} must be numeric')
    if not isfinite(value):
        raise ValueError(f'{label} must be finite')


def main() -> int:
    parser = argparse.ArgumentParser(description='Generate human-confirmed dry-run trade plans from alert/watch events.')
    parser.add_argument('--input', type=Path, default=Path('data/candidate_events.jsonl'))
    parser.add_argument('--risk-config', type=Path, default=Path('config/risk_limits.json'))
    parser.add_argument('--daily-loss-percent', type=float, default=0.0)
    parser.add_argument('--output', type=Path, default=Path('data/trade_plans.json'))
    args = parser.parse_args()

    plans = build_trade_plans(load_events(args.input), load_risk_limits(args.risk_config), args.daily_loss_percent)
    write_json(plans, args.output)
    print(f'wrote {len(plans)} trade plan records to {args.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
