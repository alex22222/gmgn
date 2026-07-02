import unittest
from pathlib import Path
from unittest.mock import patch

from gmgn_monitor.config import load_threshold_config
from gmgn_monitor.replay import print_summary, replay_source
from gmgn_monitor.replay import replay


class ListSource:
    def __init__(self, records):
        self.records = records

    def load(self):
        return iter(self.records)


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
    return data


class ReplayTest(unittest.TestCase):
    def test_replay_adds_empty_outcome_without_affecting_decision(self):
        result = replay_source(ListSource([candidate()]))[0]

        self.assertEqual(result['decision'], 'alert')
        self.assertEqual(result['score'], 100)
        self.assertEqual(result['outcome']['reviewed'], False)
        self.assertIsNone(result['outcome']['price_change_5m_percent'])

    def test_chain_specific_thresholds_allow_base_and_bsc_fixtures(self):
        config = load_threshold_config(Path('config/thresholds.json'))
        results = replay(Path('fixtures/chain_threshold_candidates.jsonl'), threshold_config=config)

        self.assertEqual([result['decision'] for result in results], ['alert', 'alert'])

    def test_malformed_fixture_fails_before_alerting(self):
        with self.assertRaises(ValueError):
            replay(Path('fixtures/malformed_candidate.jsonl'))

    def test_missing_field_fixture_fails_before_alerting(self):
        with self.assertRaisesRegex(ValueError, 'missing field: tax_risk'):
            replay(Path('fixtures/missing_field_candidate.jsonl'))

    def test_boolean_numeric_field_fails_before_alerting(self):
        with self.assertRaisesRegex(ValueError, 'liquidity must be numeric'):
            replay_source(ListSource([candidate(liquidity=True)]))

    def test_negative_numeric_field_fails_before_alerting(self):
        with self.assertRaisesRegex(ValueError, 'volume_5m must be non-negative'):
            replay_source(ListSource([candidate(volume_5m=-1)]))

    def test_non_finite_numeric_field_fails_before_alerting(self):
        with self.assertRaisesRegex(ValueError, 'volume_5m must be finite'):
            replay_source(ListSource([candidate(volume_5m=float('nan'))]))

    def test_fractional_count_field_fails_before_alerting(self):
        with self.assertRaisesRegex(ValueError, 'tx_count_1m must be an integer'):
            replay_source(ListSource([candidate(tx_count_1m=12.5)]))

    def test_integer_valued_float_count_field_passes(self):
        result = replay_source(ListSource([candidate(tx_count_1m=85.0, holder_count=280.0)]))[0]

        self.assertEqual(result['decision'], 'alert')

    def test_percent_field_above_100_fails_before_alerting(self):
        with self.assertRaisesRegex(ValueError, 'top10_holder_percent must be at most 100'):
            replay_source(ListSource([candidate(top10_holder_percent=101)]))

    def test_empty_string_field_fails_before_alerting(self):
        with self.assertRaisesRegex(ValueError, 'token_address must be non-empty'):
            replay_source(ListSource([candidate(token_address='   ')]))

    def test_invalid_detected_at_timestamp_fails_before_alerting(self):
        with self.assertRaisesRegex(ValueError, 'detected_at must be ISO timestamp'):
            replay_source(ListSource([candidate(detected_at='not-a-time')]))

    def test_summary_only_suppresses_record_details(self):
        results = [
            {'decision': 'alert', 'score': 100, 'symbol': 'AAA', 'token_address': 'Addr', 'reasons': ['ok']},
            {'decision': 'reject', 'score': 0, 'symbol': 'BBB', 'token_address': 'Addr', 'reasons': ['bad']},
        ]

        with patch('builtins.print') as mocked_print:
            print_summary(results, details=False)

        printed = [call.args[0] for call in mocked_print.call_args_list]
        self.assertEqual(printed, ['summary: alert=1 watch=0 reject=1'])


if __name__ == '__main__':
    unittest.main()
