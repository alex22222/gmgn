from __future__ import annotations

from dataclasses import dataclass

from .schema import Candidate


@dataclass(frozen=True)
class Thresholds:
    min_liquidity: float = 100.0
    min_volume_5m: float = 600.0
    min_tx_count_1m: float = 60.0
    max_top10_holder_percent: float = 30.0
    max_dev_holding_percent: float = 5.0
    max_insider_or_rat_percent: float = 20.0
    alert_score: int = 80
    watch_score: int = 55


def score_candidate(candidate: Candidate, thresholds: Thresholds | None = None) -> dict:
    thresholds = thresholds or Thresholds()
    reasons: list[str] = []
    score = 0

    hard_reject = _hard_reject_reasons(candidate, thresholds)
    if hard_reject:
        return {
            **candidate.data,
            'score': 0,
            'decision': 'reject',
            'reasons': hard_reject,
        }

    score += _add_score(candidate.get('liquidity') >= thresholds.min_liquidity, 20, reasons, 'liquidity meets minimum')
    score += _add_score(candidate.get('volume_5m') >= thresholds.min_volume_5m, 15, reasons, '5m volume meets minimum')
    score += _add_score(candidate.get('tx_count_1m') >= thresholds.min_tx_count_1m, 15, reasons, '1m transaction count meets minimum')
    score += _add_score(candidate.get('holder_count') >= 100, 10, reasons, 'holder count is broad enough')
    score += _add_score(candidate.get('top10_holder_percent') <= 20, 10, reasons, 'top10 concentration is strong')
    score += _add_score(candidate.get('dev_holding_percent') <= 2, 10, reasons, 'developer holding is low')
    score += _add_score(candidate.get('insider_or_rat_percent') <= 10, 10, reasons, 'insider or rat wallet ratio is low')
    score += _add_score(candidate.get('bundle_buy_percent') <= 10, 10, reasons, 'bundle buy ratio is low')

    if score >= thresholds.alert_score:
        decision = 'alert'
    elif score >= thresholds.watch_score:
        decision = 'watch'
    else:
        decision = 'reject'
        reasons.append('score below watch threshold')

    return {
        **candidate.data,
        'score': score,
        'decision': decision,
        'reasons': reasons,
    }


def _hard_reject_reasons(candidate: Candidate, thresholds: Thresholds) -> list[str]:
    reasons: list[str] = []

    if candidate.get('honeypot_risk'):
        reasons.append('honeypot risk present')
    if candidate.get('blacklist_risk'):
        reasons.append('blacklist risk present')
    if candidate.get('tax_risk'):
        reasons.append('tax risk present')
    if not candidate.get('mint_renounced'):
        reasons.append('mint authority is not renounced')
    if not candidate.get('freeze_renounced'):
        reasons.append('freeze authority is not renounced')
    if not candidate.get('lp_burned_or_locked'):
        reasons.append('LP is not burned or locked')
    if candidate.get('top10_holder_percent') > thresholds.max_top10_holder_percent:
        reasons.append('top10 holder concentration exceeds threshold')
    if candidate.get('dev_holding_percent') > thresholds.max_dev_holding_percent:
        reasons.append('developer holding exceeds threshold')
    if candidate.get('insider_or_rat_percent') > thresholds.max_insider_or_rat_percent:
        reasons.append('insider or rat wallet ratio exceeds threshold')

    return reasons


def _add_score(condition: bool, points: int, reasons: list[str], reason: str) -> int:
    if condition:
        reasons.append(reason)
        return points
    return 0

