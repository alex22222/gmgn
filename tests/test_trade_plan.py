import tempfile
import unittest
from pathlib import Path

from gmgn_monitor.trade_plan import build_trade_plans, load_risk_limits


RISK_LIMITS = {
    'daily_loss_limit_percent': 5.0,
    'max_single_position_percent': 2.0,
    'default_stop_loss_percent': -40.0,
    'take_profit_steps': [
        {'price_change_percent': 100.0, 'sell_percent': 50.0},
        {'price_change_percent': 300.0, 'sell_percent': 50.0},
    ],
}


def event(decision='alert'):
    return {
        'decision': decision,
        'symbol': 'GOOD',
        'chain': 'solana',
        'token_address': 'Good111111111111111111111111111111111111111',
        'score': 100,
        'reasons': ['liquidity meets minimum', '5m volume meets minimum'],
    }


class TradePlanTest(unittest.TestCase):
    def test_loads_valid_risk_limits(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'risk_limits.json'
            path.write_text(
                '{"daily_loss_limit_percent":5,"max_single_position_percent":2,"default_stop_loss_percent":-40,'
                '"take_profit_steps":[{"price_change_percent":100,"sell_percent":50},{"price_change_percent":300,"sell_percent":50}]}',
                encoding='utf-8',
            )

            limits = load_risk_limits(path)

        self.assertEqual(limits['daily_loss_limit_percent'], 5)
        self.assertEqual(limits['take_profit_steps'][0]['sell_percent'], 50)

    def test_builds_human_confirmation_plan(self):
        plan = build_trade_plans([event('alert')], RISK_LIMITS)[0]

        self.assertEqual(plan['status'], 'needs_human_confirmation')
        self.assertEqual(plan['max_position_percent'], 2.0)
        self.assertIn('invalidation_rule', plan)
        self.assertEqual(plan['exit_plan']['stop_loss_percent'], -40.0)
        self.assertIn('Confirm token address', plan['manual_checklist'][0])

    def test_reject_events_do_not_create_plans(self):
        self.assertEqual(build_trade_plans([event('reject')], RISK_LIMITS), [])

    def test_daily_loss_limit_blocks_plans(self):
        plans = build_trade_plans([event('alert')], RISK_LIMITS, daily_loss_percent=5.0)

        self.assertEqual(plans[0]['status'], 'blocked')
        self.assertEqual(plans[0]['reason'], 'daily loss limit reached')

    def test_risk_limits_must_be_object(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'risk_limits.json'
            path.write_text('[]', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, 'risk limits config must be an object'):
                load_risk_limits(path)

    def test_invalid_risk_limits_json_reports_path_and_line(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'risk_limits.json'
            path.write_text('{\nnot-json\n', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, r'risk_limits\.json:2: invalid risk limits JSON:'):
                load_risk_limits(path)

    def test_invalid_risk_limits_utf8_reports_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'risk_limits.json'
            path.write_bytes(b'\xff')

            with self.assertRaisesRegex(ValueError, r'risk_limits\.json: invalid risk limits UTF-8:'):
                load_risk_limits(path)

    def test_risk_limits_read_error_reports_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'risk_limits.json'
            path.mkdir()

            with self.assertRaisesRegex(ValueError, r'risk_limits\.json: invalid risk limits read:'):
                load_risk_limits(path)

    def test_risk_limits_require_known_fields(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'risk_limits.json'
            path.write_text('{"daily_loss_limit_percent":5}', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, 'missing risk limit field: max_single_position_percent'):
                load_risk_limits(path)

    def test_risk_limit_numbers_reject_bool(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'risk_limits.json'
            path.write_text(
                '{"daily_loss_limit_percent":true,"max_single_position_percent":2,"default_stop_loss_percent":-40,'
                '"take_profit_steps":[{"price_change_percent":100,"sell_percent":100}]}',
                encoding='utf-8',
            )

            with self.assertRaisesRegex(ValueError, 'daily_loss_limit_percent must be numeric'):
                load_risk_limits(path)

    def test_position_and_loss_limits_must_be_positive(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'risk_limits.json'
            path.write_text(
                '{"daily_loss_limit_percent":0,"max_single_position_percent":2,"default_stop_loss_percent":-40,'
                '"take_profit_steps":[{"price_change_percent":100,"sell_percent":100}]}',
                encoding='utf-8',
            )

            with self.assertRaisesRegex(ValueError, 'daily_loss_limit_percent must be greater than 0'):
                load_risk_limits(path)

    def test_stop_loss_must_be_negative(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'risk_limits.json'
            path.write_text(
                '{"daily_loss_limit_percent":5,"max_single_position_percent":2,"default_stop_loss_percent":40,'
                '"take_profit_steps":[{"price_change_percent":100,"sell_percent":100}]}',
                encoding='utf-8',
            )

            with self.assertRaisesRegex(ValueError, 'default_stop_loss_percent must be negative'):
                load_risk_limits(path)

    def test_take_profit_steps_must_sum_to_100_percent(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'risk_limits.json'
            path.write_text(
                '{"daily_loss_limit_percent":5,"max_single_position_percent":2,"default_stop_loss_percent":-40,'
                '"take_profit_steps":[{"price_change_percent":100,"sell_percent":60},{"price_change_percent":300,"sell_percent":60}]}',
                encoding='utf-8',
            )

            with self.assertRaisesRegex(ValueError, 'take_profit_steps sell_percent values must sum to 100'):
                load_risk_limits(path)


if __name__ == '__main__':
    unittest.main()
