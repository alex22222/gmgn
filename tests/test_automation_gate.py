import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from gmgn_monitor.automation_gate import build_gate_report, evaluate_gate, load_config, main


VALID_CONFIG = {
    'positive_expectancy_after_costs': True,
    'reviewed_candidate_count': 200,
    'minimum_reviewed_candidate_count': 200,
    'paper_or_shadow_results_available': True,
    'kill_switch_configured': True,
    'mandatory_logs_configured': True,
    'hard_daily_loss_limit_configured': True,
    'security_review_completed': True,
    'allows_martingale': False,
    'allows_dca_into_losers': False,
    'allows_unlimited_retries': False,
}


class AutomationGateTest(unittest.TestCase):
    def test_blocks_when_evidence_is_missing(self):
        config = dict(VALID_CONFIG)
        config['positive_expectancy_after_costs'] = False

        result = evaluate_gate(config)

        self.assertEqual(result['status'], 'blocked')
        self.assertIn('positive expectancy after costs is not proven', result['blockers'])

    def test_blocks_disallowed_strategy_shapes(self):
        config = dict(VALID_CONFIG)
        config['allows_martingale'] = True

        result = evaluate_gate(config)

        self.assertEqual(result['status'], 'blocked')
        self.assertIn('martingale is not allowed', result['blockers'])

    def test_allows_tiny_size_testing_only_when_all_gates_pass(self):
        result = evaluate_gate(VALID_CONFIG)

        self.assertEqual(result['status'], 'eligible_for_tiny_size_testing')
        self.assertEqual(result['blockers'], [])

    def test_report_states_no_execution(self):
        report = build_gate_report(VALID_CONFIG)

        self.assertIn('does not execute trades or enable signing', report)

    def test_invalid_config_json_reports_path_and_line(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'automation_gate.json'
            path.write_text('{\nnot-json\n', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, r'automation_gate\.json:2: invalid automation gate config JSON:'):
                load_config(path)

    def test_invalid_config_utf8_reports_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'automation_gate.json'
            path.write_bytes(b'\xff')

            with self.assertRaisesRegex(ValueError, r'automation_gate\.json: invalid automation gate config UTF-8:'):
                load_config(path)

    def test_config_read_error_reports_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'automation_gate.json'
            path.mkdir()

            with self.assertRaisesRegex(ValueError, r'automation_gate\.json: invalid automation gate config read:'):
                load_config(path)

    def test_main_writes_gate_report_without_execution_language_drift(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / 'automation_gate.json'
            output_path = Path(tmp_dir) / 'gate.md'
            config_path.write_text(json.dumps(VALID_CONFIG), encoding='utf-8')
            stdout = io.StringIO()
            stderr = io.StringIO()

            with patch('sys.argv', ['automation_gate', '--config', str(config_path), '--output', str(output_path)]):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = main()

            self.assertEqual(code, 0)
            self.assertEqual(stderr.getvalue(), '')
            self.assertIn('wrote automation gate report', stdout.getvalue())
            report = output_path.read_text(encoding='utf-8')
            self.assertIn('Status: eligible_for_tiny_size_testing', report)
            self.assertIn('does not execute trades or enable signing', report)

    def test_main_reports_invalid_config_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / 'automation_gate.json'
            output_path = Path(tmp_dir) / 'gate.md'
            config_path.write_text('not-json\n', encoding='utf-8')
            stdout = io.StringIO()
            stderr = io.StringIO()

            with patch('sys.argv', ['automation_gate', '--config', str(config_path), '--output', str(output_path)]):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = main()

            self.assertEqual(code, 2)
            self.assertEqual(stdout.getvalue(), '')
            self.assertIn('invalid automation gate input:', stderr.getvalue())
            self.assertIn('invalid automation gate config JSON', stderr.getvalue())
            self.assertNotIn('Traceback', stderr.getvalue())
            self.assertFalse(output_path.exists())

    def test_main_reports_write_error_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / 'automation_gate.json'
            output_path = Path(tmp_dir) / 'gate.md'
            output_path.mkdir()
            config_path.write_text(json.dumps(VALID_CONFIG), encoding='utf-8')
            stdout = io.StringIO()
            stderr = io.StringIO()

            with patch('sys.argv', ['automation_gate', '--config', str(config_path), '--output', str(output_path)]):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = main()

            self.assertEqual(code, 2)
            self.assertEqual(stdout.getvalue(), '')
            self.assertIn('failed to write automation gate report:', stderr.getvalue())
            self.assertNotIn('Traceback', stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
