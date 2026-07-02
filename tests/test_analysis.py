import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from gmgn_monitor.analysis import build_analysis_report, main


def event(decision='alert', score=100):
    return {
        'decision': decision,
        'score': score,
        'outcome': {
            'reviewed': decision != 'reject',
            'price_change_5m_percent': 10.0,
            'price_change_30m_percent': 20.0,
            'price_change_24h_percent': 30.0,
            'max_drawdown_percent': -5.0,
        },
    }


class AnalysisTest(unittest.TestCase):
    def test_builds_score_and_outcome_analysis(self):
        report = build_analysis_report([
            {
                'decision': 'alert',
                'score': 100,
                'outcome': {
                    'reviewed': True,
                    'price_change_5m_percent': 10.0,
                    'price_change_30m_percent': 20.0,
                    'price_change_24h_percent': 30.0,
                    'max_drawdown_percent': -5.0,
                },
            },
            {
                'decision': 'watch',
                'score': 60,
                'outcome': {
                    'reviewed': True,
                    'price_change_5m_percent': -2.0,
                    'price_change_30m_percent': 4.0,
                    'price_change_24h_percent': 8.0,
                    'max_drawdown_percent': -12.0,
                },
            },
            {
                'decision': 'reject',
                'score': 0,
                'outcome': {'reviewed': False},
            },
        ])

        self.assertIn('| 0-24 | 1 |', report)
        self.assertIn('| 50-74 | 1 |', report)
        self.assertIn('| 75-100 | 1 |', report)
        self.assertIn('| alert | 1 | 10.00 | 20.00 | 30.00 | -5.00 |', report)
        self.assertIn('| watch | 1 | -2.00 | 4.00 | 8.00 | -12.00 |', report)

    def test_main_writes_analysis_report(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / 'events.jsonl'
            output_path = Path(tmp_dir) / 'analysis.md'
            input_path.write_text(json.dumps(event('alert', 100)) + '\n' + json.dumps(event('reject', 0)) + '\n', encoding='utf-8')
            stdout = io.StringIO()
            stderr = io.StringIO()

            with patch('sys.argv', ['analysis', '--input', str(input_path), '--output', str(output_path)]):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = main()

            self.assertEqual(code, 0)
            self.assertEqual(stderr.getvalue(), '')
            self.assertIn('wrote outcome analysis', stdout.getvalue())
            report = output_path.read_text(encoding='utf-8')
            self.assertIn('Total candidates: 2', report)
            self.assertIn('Reviewed candidates: 1', report)

    def test_main_reports_invalid_input_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / 'events.jsonl'
            output_path = Path(tmp_dir) / 'analysis.md'
            input_path.write_text('not-json\n', encoding='utf-8')
            stdout = io.StringIO()
            stderr = io.StringIO()

            with patch('sys.argv', ['analysis', '--input', str(input_path), '--output', str(output_path)]):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = main()

            self.assertEqual(code, 2)
            self.assertEqual(stdout.getvalue(), '')
            self.assertIn('invalid analysis input:', stderr.getvalue())
            self.assertNotIn('Traceback', stderr.getvalue())
            self.assertFalse(output_path.exists())

    def test_main_reports_write_error_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / 'events.jsonl'
            output_path = Path(tmp_dir) / 'analysis.md'
            input_path.write_text(json.dumps(event('alert', 100)) + '\n', encoding='utf-8')
            output_path.mkdir()
            stdout = io.StringIO()
            stderr = io.StringIO()

            with patch('sys.argv', ['analysis', '--input', str(input_path), '--output', str(output_path)]):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = main()

            self.assertEqual(code, 2)
            self.assertEqual(stdout.getvalue(), '')
            self.assertIn('failed to write analysis report:', stderr.getvalue())
            self.assertNotIn('Traceback', stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
