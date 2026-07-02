from __future__ import annotations

from dataclasses import fields
from math import isfinite
from pathlib import Path
from typing import Any

from .scoring import Thresholds
from .serialization import load_json


class ThresholdConfig:
    def __init__(self, default: Thresholds | None = None, chains: dict[str, Thresholds] | None = None):
        self.default = default or Thresholds()
        self.chains = chains or {}

    def for_chain(self, chain: str) -> Thresholds:
        return self.chains.get(chain.lower(), self.default)


def load_threshold_config(path: Path) -> ThresholdConfig:
    raw = load_json(path, label='threshold config')
    if not isinstance(raw, dict):
        raise ValueError('threshold config must be an object')

    default_values = raw.get('default', {})
    if not isinstance(default_values, dict):
        raise ValueError('default thresholds must be an object')

    chain_values = raw.get('chains', {})
    if not isinstance(chain_values, dict):
        raise ValueError('chains thresholds must be an object')

    default = _thresholds_from_dict(default_values, Thresholds(), 'default')
    chains = {
        chain.lower(): _thresholds_from_dict(values, default, chain.lower())
        for chain, values in chain_values.items()
    }
    return ThresholdConfig(default=default, chains=chains)


def _thresholds_from_dict(values: dict[str, Any], base: Thresholds, label: str) -> Thresholds:
    if not isinstance(values, dict):
        raise ValueError(f'{label} thresholds must be an object')

    allowed = {field.name for field in fields(Thresholds)}
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ValueError(f'unknown threshold fields: {", ".join(unknown)}')

    merged = {field.name: getattr(base, field.name) for field in fields(Thresholds)}
    merged.update(values)
    _validate_threshold_values(merged)
    return Thresholds(**merged)


def _validate_threshold_values(values: dict[str, Any]) -> None:
    percent_fields = {
        'max_top10_holder_percent',
        'max_dev_holding_percent',
        'max_insider_or_rat_percent',
    }

    for name, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f'{name} must be numeric')
        if not isfinite(value):
            raise ValueError(f'{name} must be finite')
        if value < 0:
            raise ValueError(f'{name} must be non-negative')
        if name in percent_fields and value > 100:
            raise ValueError(f'{name} must be at most 100')

    if values['alert_score'] < values['watch_score']:
        raise ValueError('alert_score must be greater than or equal to watch_score')
