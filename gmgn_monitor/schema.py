from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any

from .time_utils import is_iso_timestamp


REQUIRED_FIELDS = (
    'chain',
    'token_address',
    'symbol',
    'detected_at',
    'source',
    'liquidity',
    'market_cap',
    'volume_1m',
    'volume_5m',
    'tx_count_1m',
    'holder_count',
    'top10_holder_percent',
    'dev_holding_percent',
    'insider_or_rat_percent',
    'bundle_buy_percent',
    'mint_renounced',
    'freeze_renounced',
    'lp_burned_or_locked',
    'honeypot_risk',
    'blacklist_risk',
    'tax_risk',
)


NUMERIC_FIELDS = (
    'liquidity',
    'market_cap',
    'volume_1m',
    'volume_5m',
    'tx_count_1m',
    'holder_count',
    'top10_holder_percent',
    'dev_holding_percent',
    'insider_or_rat_percent',
    'bundle_buy_percent',
)


PERCENT_FIELDS = (
    'top10_holder_percent',
    'dev_holding_percent',
    'insider_or_rat_percent',
    'bundle_buy_percent',
)


COUNT_FIELDS = (
    'tx_count_1m',
    'holder_count',
)


BOOLEAN_FIELDS = (
    'mint_renounced',
    'freeze_renounced',
    'lp_burned_or_locked',
    'honeypot_risk',
    'blacklist_risk',
    'tax_risk',
)


@dataclass(frozen=True)
class Candidate:
    data: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'Candidate':
        errors = validate_candidate_data(data)
        if errors:
            raise ValueError('; '.join(errors))
        return cls(data)

    def get(self, field: str) -> Any:
        return self.data[field]


def validate_candidate_data(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    for field in REQUIRED_FIELDS:
        if field not in data:
            errors.append(f'missing field: {field}')

    for field in NUMERIC_FIELDS:
        if field in data and (isinstance(data[field], bool) or not isinstance(data[field], (int, float))):
            errors.append(f'{field} must be numeric')
        elif field in data and not isfinite(data[field]):
            errors.append(f'{field} must be finite')
        elif field in data and data[field] < 0:
            errors.append(f'{field} must be non-negative')

    for field in PERCENT_FIELDS:
        if field in data and isinstance(data[field], (int, float)) and not isinstance(data[field], bool) and data[field] > 100:
            errors.append(f'{field} must be at most 100')

    for field in COUNT_FIELDS:
        if field in data and isinstance(data[field], (int, float)) and not isinstance(data[field], bool) and isfinite(data[field]) and not float(data[field]).is_integer():
            errors.append(f'{field} must be an integer')

    for field in BOOLEAN_FIELDS:
        if field in data and not isinstance(data[field], bool):
            errors.append(f'{field} must be boolean')

    for field in ('chain', 'token_address', 'symbol', 'detected_at', 'source'):
        if field in data and not isinstance(data[field], str):
            errors.append(f'{field} must be string')
        elif field in data and not data[field].strip():
            errors.append(f'{field} must be non-empty')

    if isinstance(data.get('detected_at'), str) and data['detected_at'].strip() and not is_iso_timestamp(data['detected_at']):
        errors.append('detected_at must be ISO timestamp')

    return errors
