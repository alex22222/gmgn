import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from gmgn_monitor.sample_data import generate_candidates, main, write_jsonl
from gmgn_monitor.schema import Candidate
from gmgn_monitor.scoring import score_candidate


class SampleDataTest(unittest.TestCase):
    def test_generates_schema_valid_candidates(self):
        records = generate_candidates(200)

        self.assertEqual(len(records), 200)
        for record in records:
            Candidate.from_dict(record)

    def test_generates_mixed_decisions(self):
        decisions = [
            score_candidate(Candidate.from_dict(record))['decision']
            for record in generate_candidates(5)
        ]

        self.assertEqual(decisions, ['alert', 'watch', 'reject', 'reject', 'reject'])

    def test_rejects_negative_count(self):
        with self.assertRaisesRegex(ValueError, 'sample candidate count must be non-negative'):
            generate_candidates(-1)

    def test_write_jsonl_uses_jsonl_format_for_empty_and_nonempty_records(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / 'samples.jsonl'

            write_jsonl(generate_candidates(1), output_path)
            nonempty = output_path.read_text(encoding='utf-8')
            write_jsonl([], output_path)
            empty = output_path.read_text(encoding='utf-8')

            self.assertIn('"symbol": "SMP000"', nonempty)
            self.assertEqual(empty, '')

    def test_main_writes_sample_candidates(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / 'samples.jsonl'
            stdout = io.StringIO()
            stderr = io.StringIO()

            with patch('sys.argv', ['sample_data', '--count', '2', '--output', str(output_path)]):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = main()

            self.assertEqual(code, 0)
            self.assertEqual(stderr.getvalue(), '')
            self.assertIn('wrote 2 sample candidates', stdout.getvalue())
            self.assertEqual(len(output_path.read_text(encoding='utf-8').splitlines()), 2)

    def test_main_reports_invalid_count_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / 'samples.jsonl'
            stdout = io.StringIO()
            stderr = io.StringIO()

            with patch('sys.argv', ['sample_data', '--count', '-1', '--output', str(output_path)]):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = main()

            self.assertEqual(code, 2)
            self.assertEqual(stdout.getvalue(), '')
            self.assertIn('invalid sample-data input:', stderr.getvalue())
            self.assertNotIn('Traceback', stderr.getvalue())
            self.assertFalse(output_path.exists())

    def test_main_reports_write_error_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / 'samples.jsonl'
            output_path.mkdir()
            stdout = io.StringIO()
            stderr = io.StringIO()

            with patch('sys.argv', ['sample_data', '--count', '1', '--output', str(output_path)]):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = main()

            self.assertEqual(code, 2)
            self.assertEqual(stdout.getvalue(), '')
            self.assertIn('failed to write sample candidates:', stderr.getvalue())
            self.assertNotIn('Traceback', stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
