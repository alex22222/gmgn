import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from gmgn_monitor.execution_eval import build_execution_report, load_venues, main, rank_venues


def valid_venue(name='GMGN'):
    return {
        'name': name,
        'role': 'data_and_execution',
        'estimated_fee_percent': 1.0,
        'latency_tier': 'seconds',
        'custody_risk': 'external_execution_surface',
        'reliability_status': 'needs_live_measurement',
        'notes': 'Measure before use.',
    }


class ExecutionEvalTest(unittest.TestCase):
    def test_ranks_by_fee_then_custody_risk(self):
        venues = [
            {'name': 'B', 'estimated_fee_percent': 1.0, 'custody_risk': 'bot_wallet_surface', 'reliability_status': 'needs_live_measurement'},
            {'name': 'A', 'estimated_fee_percent': 0.5, 'custody_risk': 'external_execution_surface', 'reliability_status': 'needs_live_measurement'},
        ]

        self.assertEqual([venue['name'] for venue in rank_venues(venues)], ['A', 'B'])

    def test_not_implemented_venue_is_penalized(self):
        venues = [
            {'name': 'Direct', 'estimated_fee_percent': 0.0, 'custody_risk': 'self_custody_engineering_risk', 'reliability_status': 'not_implemented'},
            {'name': 'MeasuredCandidate', 'estimated_fee_percent': 1.0, 'custody_risk': 'external_execution_surface', 'reliability_status': 'needs_live_measurement'},
        ]

        self.assertEqual([venue['name'] for venue in rank_venues(venues)], ['MeasuredCandidate', 'Direct'])

    def test_report_is_evaluation_only(self):
        report = build_execution_report([
            {
                'name': 'GMGN',
                'role': 'data_and_execution',
                'estimated_fee_percent': 1.0,
                'latency_tier': 'seconds',
                'custody_risk': 'external_execution_surface',
                'reliability_status': 'needs_live_measurement',
                'notes': 'Measure before use.',
            },
        ])

        self.assertIn('evaluation-only', report)
        self.assertIn('does not integrate with wallets', report)
        self.assertIn('| 1 | GMGN |', report)

    def test_load_venues_reports_invalid_json_with_path_and_line(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'execution_venues.json'
            path.write_text('{\nnot-json\n', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, r'execution_venues\.json:2: invalid execution venues JSON:'):
                load_venues(path)

    def test_load_venues_reports_invalid_utf8_with_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'execution_venues.json'
            path.write_bytes(b'\xff')

            with self.assertRaisesRegex(ValueError, r'execution_venues\.json: invalid execution venues UTF-8:'):
                load_venues(path)

    def test_load_venues_reports_read_error_with_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'execution_venues.json'
            path.mkdir()

            with self.assertRaisesRegex(ValueError, r'execution_venues\.json: invalid execution venues read:'):
                load_venues(path)

    def test_load_venues_rejects_bad_shape_before_ranking(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'execution_venues.json'
            path.write_text('[{"name":"GMGN"}]', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, 'execution venue 1 missing field: role'):
                load_venues(path)

    def test_main_writes_execution_evaluation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / 'execution_venues.json'
            output_path = Path(tmp_dir) / 'execution.md'
            input_path.write_text(json.dumps([valid_venue()]), encoding='utf-8')
            stdout = io.StringIO()
            stderr = io.StringIO()

            with patch('sys.argv', ['execution_eval', '--input', str(input_path), '--output', str(output_path)]):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = main()

            self.assertEqual(code, 0)
            self.assertEqual(stderr.getvalue(), '')
            self.assertIn('wrote execution evaluation', stdout.getvalue())
            report = output_path.read_text(encoding='utf-8')
            self.assertIn('evaluation-only', report)
            self.assertIn('| 1 | GMGN |', report)

    def test_main_reports_invalid_input_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / 'execution_venues.json'
            output_path = Path(tmp_dir) / 'execution.md'
            input_path.write_text('not-json\n', encoding='utf-8')
            stdout = io.StringIO()
            stderr = io.StringIO()

            with patch('sys.argv', ['execution_eval', '--input', str(input_path), '--output', str(output_path)]):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = main()

            self.assertEqual(code, 2)
            self.assertEqual(stdout.getvalue(), '')
            self.assertIn('invalid execution evaluation input:', stderr.getvalue())
            self.assertIn('invalid execution venues JSON', stderr.getvalue())
            self.assertNotIn('Traceback', stderr.getvalue())
            self.assertFalse(output_path.exists())

    def test_main_reports_write_error_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / 'execution_venues.json'
            output_path = Path(tmp_dir) / 'execution.md'
            input_path.write_text(json.dumps([valid_venue()]), encoding='utf-8')
            output_path.mkdir()
            stdout = io.StringIO()
            stderr = io.StringIO()

            with patch('sys.argv', ['execution_eval', '--input', str(input_path), '--output', str(output_path)]):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = main()

            self.assertEqual(code, 2)
            self.assertEqual(stdout.getvalue(), '')
            self.assertIn('failed to write execution evaluation:', stderr.getvalue())
            self.assertNotIn('Traceback', stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
