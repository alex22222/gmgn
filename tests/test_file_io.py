import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

from gmgn_monitor.file_io import (
    LockAcquisitionError,
    atomic_write_json,
    atomic_write_jsonl,
    atomic_write_text,
    describe_lock,
    describe_temp_artifacts,
    durable_append_text,
    exclusive_file_lock,
)


class FileIoTest(unittest.TestCase):
    def test_atomic_write_text_replaces_existing_file_without_temp_leftovers(self):
        with TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / 'artifact.txt'
            output.write_text('old\n', encoding='utf-8')

            atomic_write_text('new\n', output)

            self.assertEqual(output.read_text(encoding='utf-8'), 'new\n')
            self.assertEqual(list(Path(temp_dir).glob('.artifact.txt.*.tmp')), [])

    def test_atomic_write_jsonl_writes_sorted_json_lines(self):
        with TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / 'events.jsonl'

            atomic_write_jsonl([{'b': 2, 'a': 1}], output)

            self.assertEqual(output.read_text(encoding='utf-8'), '{"a": 1, "b": 2}\n')

    def test_atomic_write_json_writes_pretty_json_list(self):
        with TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / 'plans.json'

            atomic_write_json([{'b': 2, 'a': 1}], output)

            self.assertEqual(json.loads(output.read_text(encoding='utf-8')), [{'a': 1, 'b': 2}])

    def test_durable_append_text_appends_and_creates_parent_directory(self):
        with TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / 'reports/history.jsonl'

            durable_append_text('one\n', output)
            durable_append_text('two\n', output)

            self.assertEqual(output.read_text(encoding='utf-8'), 'one\ntwo\n')

    def test_describe_lock_reports_missing_lock(self):
        with TemporaryDirectory() as temp_dir:
            lock = describe_lock(Path(temp_dir) / 'verification.lock')

        self.assertFalse(lock['exists'])
        self.assertFalse(lock['stale'])
        self.assertIsNone(lock['age_seconds'])

    def test_describe_lock_reports_fresh_lock(self):
        with TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / 'verification.lock'
            lock_path.write_text('fresh\n', encoding='utf-8')

            lock = describe_lock(lock_path, stale_after_seconds=3600)

        self.assertTrue(lock['exists'])
        self.assertFalse(lock['stale'])
        self.assertIsInstance(lock['age_seconds'], int)

    def test_describe_lock_reports_stale_lock(self):
        with TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / 'verification.lock'
            lock_path.write_text('stale\n', encoding='utf-8')
            old_time = time.time() - 7200
            os.utime(lock_path, (old_time, old_time))

            lock = describe_lock(lock_path, stale_after_seconds=3600)

        self.assertTrue(lock['exists'])
        self.assertTrue(lock['stale'])
        self.assertGreaterEqual(lock['age_seconds'], 3600)

    def test_describe_temp_artifacts_reports_counts(self):
        with TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            fresh = base / '.artifact.txt.fresh.tmp'
            fresh.write_text('fresh\n', encoding='utf-8')
            stale = base / 'nested/.artifact.txt.stale.tmp'
            stale.parent.mkdir()
            stale.write_text('stale\n', encoding='utf-8')
            old_time = time.time() - 7200
            os.utime(stale, (old_time, old_time))

            status = describe_temp_artifacts(base, stale_after_seconds=3600)

        self.assertEqual(status['count'], 2)
        self.assertEqual(status['stale_count'], 1)
        self.assertTrue(any(file['stale'] for file in status['files']))

    def test_exclusive_file_lock_removes_lock_on_exit(self):
        with TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / 'verification.lock'

            with exclusive_file_lock(lock_path):
                self.assertTrue(lock_path.exists())

            self.assertFalse(lock_path.exists())

    def test_exclusive_file_lock_rejects_active_lock(self):
        with TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / 'verification.lock'

            with exclusive_file_lock(lock_path):
                with self.assertRaises(LockAcquisitionError):
                    with exclusive_file_lock(lock_path):
                        pass

    def test_exclusive_file_lock_replaces_stale_lock(self):
        with TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / 'verification.lock'
            lock_path.write_text('stale\n', encoding='utf-8')
            old_time = time.time() - 7200
            os.utime(lock_path, (old_time, old_time))

            with exclusive_file_lock(lock_path, stale_after_seconds=3600):
                self.assertTrue(lock_path.exists())

            self.assertFalse(lock_path.exists())


if __name__ == '__main__':
    unittest.main()
