import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from gmgn_monitor.report import build_markdown_report, main


def event(decision='alert'):
    return {
        'decision': decision,
        'score': 90 if decision == 'alert' else 0,
        'chain': 'solana',
        'source': 'fixture',
        'symbol': 'GOOD' if decision == 'alert' else 'BAD',
        'reasons': ['liquidity meets minimum'],
        'outcome': {'reviewed': False},
    }


class ReportTest(unittest.TestCase):
    def test_builds_summary_counts_and_notable_candidates(self):
        report = build_markdown_report([
            {
                'decision': 'alert',
                'score': 90,
                'chain': 'solana',
                'source': 'fixture',
                'symbol': 'GOOD',
                'reasons': ['liquidity meets minimum'],
            },
            {
                'decision': 'reject',
                'score': 0,
                'chain': 'base',
                'source': 'fixture',
                'symbol': 'BAD',
                'reasons': ['honeypot risk present'],
            },
        ])

        self.assertIn('| alert | 1 |', report)
        self.assertIn('| reject | 1 |', report)
        self.assertIn('| solana | 1 |', report)
        self.assertIn('| pending | 2 |', report)
        self.assertIn('| alert | 90 | solana | GOOD | liquidity meets minimum |', report)

    def test_custom_title_supports_weekly_summary(self):
        report = build_markdown_report([], title='GMGN Monitor Weekly Summary')

        self.assertIn('# GMGN Monitor Weekly Summary', report)

    def test_handles_no_alert_or_watch_candidates(self):
        report = build_markdown_report([
            {
                'decision': 'reject',
                'score': 0,
                'chain': 'solana',
                'source': 'fixture',
                'symbol': 'BAD',
                'reasons': [],
            },
        ])

        self.assertIn('No alert or watch candidates.', report)

    def test_large_sample_report_has_pending_count(self):
        events = [
            {
                'decision': 'alert' if index % 2 == 0 else 'reject',
                'score': 100 if index % 2 == 0 else 0,
                'chain': 'solana',
                'source': 'test:large',
                'symbol': f'T{index}',
                'reasons': ['ok'],
                'outcome': {'reviewed': False},
            }
            for index in range(200)
        ]

        report = build_markdown_report(events)

        self.assertIn('Total candidates: 200', report)
        self.assertIn('| pending | 200 |', report)

    def test_main_writes_report_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / 'events.jsonl'
            output_path = Path(tmp_dir) / 'summary.md'
            input_path.write_text(json.dumps(event('alert')) + '\n' + json.dumps(event('reject')) + '\n', encoding='utf-8')
            stdout = io.StringIO()
            stderr = io.StringIO()

            with patch('sys.argv', ['report', '--input', str(input_path), '--output', str(output_path)]):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = main()

            self.assertEqual(code, 0)
            self.assertEqual(stdout.getvalue(), '')
            self.assertEqual(stderr.getvalue(), '')
            report = output_path.read_text(encoding='utf-8')
            self.assertIn('Total candidates: 2', report)
            self.assertIn('| alert | 1 |', report)

    def test_main_prints_report_without_output_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / 'events.jsonl'
            input_path.write_text(json.dumps(event('alert')) + '\n', encoding='utf-8')
            stdout = io.StringIO()
            stderr = io.StringIO()

            with patch('sys.argv', ['report', '--input', str(input_path), '--title', 'Custom Summary']):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = main()

            self.assertEqual(code, 0)
            self.assertEqual(stderr.getvalue(), '')
            self.assertIn('# Custom Summary', stdout.getvalue())
            self.assertIn('Total candidates: 1', stdout.getvalue())

    def test_main_reports_invalid_input_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / 'events.jsonl'
            output_path = Path(tmp_dir) / 'summary.md'
            input_path.write_text('not-json\n', encoding='utf-8')
            stdout = io.StringIO()
            stderr = io.StringIO()

            with patch('sys.argv', ['report', '--input', str(input_path), '--output', str(output_path)]):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = main()

            self.assertEqual(code, 2)
            self.assertEqual(stdout.getvalue(), '')
            self.assertIn('invalid report input:', stderr.getvalue())
            self.assertNotIn('Traceback', stderr.getvalue())
            self.assertFalse(output_path.exists())

    def test_main_reports_write_error_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / 'events.jsonl'
            output_path = Path(tmp_dir) / 'summary.md'
            input_path.write_text(json.dumps(event('alert')) + '\n', encoding='utf-8')
            output_path.mkdir()
            stdout = io.StringIO()
            stderr = io.StringIO()

            with patch('sys.argv', ['report', '--input', str(input_path), '--output', str(output_path)]):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = main()

            self.assertEqual(code, 2)
            self.assertEqual(stdout.getvalue(), '')
            self.assertIn('failed to write report:', stderr.getvalue())
            self.assertNotIn('Traceback', stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
