import unittest

from gmgn_monitor.schema import Candidate
from gmgn_monitor.scoring import Thresholds, score_candidate


def candidate(**overrides):
    data = {
        'chain': 'solana',
        'token_address': 'Test111111111111111111111111111111111111111',
        'symbol': 'TEST',
        'detected_at': '2026-07-01T14:00:00Z',
        'source': 'test',
        'liquidity': 140.0,
        'market_cap': 69000.0,
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
    data.update(overrides)
    return Candidate.from_dict(data)


class ScoringTest(unittest.TestCase):
    def test_alert_for_strong_candidate(self):
        result = score_candidate(candidate())

        self.assertEqual(result['decision'], 'alert')
        self.assertEqual(result['score'], 100)

    def test_watch_for_partial_candidate(self):
        result = score_candidate(candidate(holder_count=70, top10_holder_percent=24.0, dev_holding_percent=3.5, bundle_buy_percent=18.0))

        self.assertEqual(result['decision'], 'watch')
        self.assertEqual(result['score'], 60)

    def test_reject_for_honeypot(self):
        result = score_candidate(candidate(honeypot_risk=True))

        self.assertEqual(result['decision'], 'reject')
        self.assertIn('honeypot risk present', result['reasons'])

    def test_reject_for_missing_required_field(self):
        data = candidate().data.copy()
        del data['liquidity']

        with self.assertRaises(ValueError):
            Candidate.from_dict(data)

    def test_configured_threshold_changes_decision(self):
        strict = Thresholds(alert_score=105, watch_score=101)
        result = score_candidate(candidate(), strict)

        self.assertEqual(result['decision'], 'reject')
        self.assertIn('score below watch threshold', result['reasons'])


if __name__ == '__main__':
    unittest.main()
