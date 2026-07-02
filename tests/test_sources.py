import tempfile
import unittest
from pathlib import Path

from gmgn_monitor.sources import JsonlCandidateSource


class JsonlCandidateSourceTest(unittest.TestCase):
    def test_loads_jsonl_records(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'records.jsonl'
            path.write_text('{"symbol":"ONE"}\n\n{"symbol":"TWO"}\n', encoding='utf-8')

            records = list(JsonlCandidateSource(path).load())

        self.assertEqual(records, [{'symbol': 'ONE'}, {'symbol': 'TWO'}])

    def test_invalid_json_includes_line_number(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'records.jsonl'
            path.write_text('{"symbol":"ONE"}\nnot-json\n', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, r'records\.jsonl:2: invalid JSONL JSON:'):
                list(JsonlCandidateSource(path).load())

    def test_non_object_record_includes_line_number(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'records.jsonl'
            path.write_text('{"symbol":"ONE"}\n[]\n', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, r'records\.jsonl:2: invalid JSONL record: expected object'):
                list(JsonlCandidateSource(path).load())

    def test_invalid_utf8_reports_path_without_unicode_traceback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'records.jsonl'
            path.write_bytes(b'\xff')

            with self.assertRaisesRegex(ValueError, r'records\.jsonl: invalid JSONL UTF-8:'):
                list(JsonlCandidateSource(path).load())

    def test_read_error_reports_path_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'records.jsonl'
            path.mkdir()

            with self.assertRaisesRegex(ValueError, r'records\.jsonl: invalid JSONL read:'):
                list(JsonlCandidateSource(path).load())


if __name__ == '__main__':
    unittest.main()
