import io
import json
import os
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from gmgn_monitor.status import (
    build_status,
    calculate_report_age_minutes,
    calculate_report_future_seconds,
    format_status,
    load_verification_report,
    main,
    report_has_required_steps,
    report_matches_latest_history,
)


class StatusTest(unittest.TestCase):
    def _ok_steps(self):
        return [
            {'name': 'pipeline', 'status': 'ok'},
            {'name': 'expectations', 'status': 'ok'},
            {'name': 'doctor', 'status': 'ok'},
            {'name': 'tests', 'status': 'ok'},
            {'name': 'safety_scan', 'status': 'ok'},
        ]

    def test_load_verification_report_returns_none_when_missing(self):
        with TemporaryDirectory() as temp_dir:
            report = load_verification_report(Path(temp_dir) / 'missing.json')

        self.assertIsNone(report)

    def test_load_verification_report_rejects_invalid_json(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'verification_report.json'
            path.write_text('not-json\n', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, 'invalid verification report JSON:'):
                load_verification_report(path)

    def test_load_verification_report_rejects_invalid_utf8(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'verification_report.json'
            path.write_bytes(b'\xff')

            with self.assertRaisesRegex(ValueError, 'invalid verification report UTF-8:'):
                load_verification_report(path)

    def test_load_verification_report_rejects_read_error(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'verification_report.json'
            path.mkdir()

            with self.assertRaisesRegex(ValueError, 'invalid verification report read:'):
                load_verification_report(path)

    def test_load_verification_report_rejects_non_object(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'verification_report.json'
            path.write_text('[]\n', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, 'invalid verification report: expected object'):
                load_verification_report(path)

    def test_main_reports_malformed_report_without_traceback(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_report.json').write_text('not-json\n', encoding='utf-8')

            stdout = io.StringIO()
            with patch('sys.argv', ['status', '--root', str(root)]):
                with redirect_stdout(stdout):
                    code = main()

        self.assertEqual(code, 1)
        self.assertIn('GMGN monitor status: invalid verification report JSON:', stdout.getvalue())

    def test_main_reports_invalid_utf8_report_without_traceback(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_report.json').write_bytes(b'\xff')

            stdout = io.StringIO()
            with patch('sys.argv', ['status', '--root', str(root)]):
                with redirect_stdout(stdout):
                    code = main()

        self.assertEqual(code, 1)
        self.assertIn('GMGN monitor status: invalid verification report UTF-8:', stdout.getvalue())

    def test_main_reports_report_read_error_without_traceback(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data/verification_report.json').mkdir(parents=True)

            stdout = io.StringIO()
            with patch('sys.argv', ['status', '--root', str(root)]):
                with redirect_stdout(stdout):
                    code = main()

        self.assertEqual(code, 1)
        self.assertIn('GMGN monitor status: invalid verification report read:', stdout.getvalue())
        self.assertNotIn('Traceback', stdout.getvalue())

    def test_main_reports_malformed_history_without_traceback(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_history.jsonl').write_text('not-json\n', encoding='utf-8')

            stdout = io.StringIO()
            with patch('sys.argv', ['status', '--root', str(root)]):
                with redirect_stdout(stdout):
                    code = main()

        self.assertEqual(code, 1)
        self.assertIn('GMGN monitor status:', stdout.getvalue())
        self.assertIn('invalid history JSON:', stdout.getvalue())

    def test_main_reports_invalid_utf8_history_without_traceback(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_history.jsonl').write_bytes(b'\xff')

            stdout = io.StringIO()
            with patch('sys.argv', ['status', '--root', str(root)]):
                with redirect_stdout(stdout):
                    code = main()

        self.assertEqual(code, 1)
        self.assertIn('GMGN monitor status:', stdout.getvalue())
        self.assertIn('invalid history UTF-8:', stdout.getvalue())

    def test_main_reports_history_read_error_without_traceback(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data/verification_history.jsonl').mkdir(parents=True)

            stdout = io.StringIO()
            with patch('sys.argv', ['status', '--root', str(root)]):
                with redirect_stdout(stdout):
                    code = main()

        self.assertEqual(code, 1)
        self.assertIn('GMGN monitor status:', stdout.getvalue())
        self.assertIn('invalid history read:', stdout.getvalue())
        self.assertNotIn('Traceback', stdout.getvalue())

    def test_build_status_is_ok_when_doctor_report_and_history_are_ok(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_report.json').write_text(
                json.dumps({'status': 'ok', 'generated_at': 'now', 'steps': self._ok_steps()}),
                encoding='utf-8',
            )
            (root / 'data/verification_history.jsonl').write_text(
                json.dumps({'status': 'ok', 'generated_at': 'now', 'steps': self._ok_steps()}) + '\n',
                encoding='utf-8',
            )

            with patch('gmgn_monitor.status.run_checks', return_value=[]):
                status = build_status(root, now=datetime(2026, 7, 1, 12, 5, tzinfo=timezone.utc))

        self.assertEqual(status['status'], 'ok')
        self.assertEqual(status['report_status'], 'ok')
        self.assertEqual(status['report_age_minutes'], None)
        self.assertEqual(status['history']['record_count'], 1)
        self.assertTrue(status['report_matches_latest_history'])
        self.assertTrue(status['report_steps_complete'])

    def test_calculate_report_age_minutes_from_iso_timestamp(self):
        age = calculate_report_age_minutes(
            '2026-07-01T12:00:00+00:00',
            datetime(2026, 7, 1, 12, 15, tzinfo=timezone.utc),
        )

        self.assertEqual(age, 15)

    def test_calculate_report_future_seconds_from_iso_timestamp(self):
        future_seconds = calculate_report_future_seconds(
            '2026-07-01T12:01:30+00:00',
            datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(future_seconds, 90)

    def test_build_status_passes_when_report_is_fresh_enough(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_report.json').write_text(
                json.dumps({
                    'status': 'ok',
                    'generated_at': '2026-07-01T12:00:00+00:00',
                    'steps': self._ok_steps(),
                }),
                encoding='utf-8',
            )

            with patch('gmgn_monitor.status.run_checks', return_value=[]):
                status = build_status(
                    root,
                    max_report_age_minutes=30,
                    now=datetime(2026, 7, 1, 12, 15, tzinfo=timezone.utc),
                )

        self.assertEqual(status['status'], 'ok')
        self.assertEqual(status['report_age_minutes'], 15)

    def test_build_status_fails_when_report_is_stale(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_report.json').write_text(
                json.dumps({
                    'status': 'ok',
                    'generated_at': '2026-07-01T12:00:00+00:00',
                    'steps': self._ok_steps(),
                }),
                encoding='utf-8',
            )

            with patch('gmgn_monitor.status.run_checks', return_value=[]):
                status = build_status(
                    root,
                    max_report_age_minutes=10,
                    now=datetime(2026, 7, 1, 12, 15, tzinfo=timezone.utc),
                )

        self.assertEqual(status['status'], 'fail')
        self.assertEqual(status['report_age_minutes'], 15)

    def test_build_status_with_report_requirement_passes_when_report_is_ok_and_timestamped(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_report.json').write_text(
                json.dumps({
                    'status': 'ok',
                    'generated_at': '2026-07-01T12:00:00+00:00',
                    'steps': self._ok_steps(),
                }),
                encoding='utf-8',
            )

            with patch('gmgn_monitor.status.run_checks', return_value=[]):
                status = build_status(
                    root,
                    require_report=True,
                    now=datetime(2026, 7, 1, 12, 15, tzinfo=timezone.utc),
                )

        self.assertEqual(status['status'], 'ok')
        self.assertEqual(status['report_age_minutes'], 15)
        self.assertTrue(status['require_report'])
        self.assertTrue(status['report_steps_complete'])
        self.assertEqual(status['report_future_seconds'], 0)

    def test_build_status_with_report_requirement_fails_without_report(self):
        with TemporaryDirectory() as temp_dir:
            with patch('gmgn_monitor.status.run_checks', return_value=[]):
                status = build_status(Path(temp_dir), require_report=True)

        self.assertEqual(status['status'], 'fail')
        self.assertIsNone(status['report_status'])
        self.assertIsNone(status['report_age_minutes'])

    def test_build_status_with_report_requirement_fails_when_report_timestamp_is_invalid(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_report.json').write_text(
                json.dumps({'status': 'ok', 'generated_at': 'not-a-timestamp', 'steps': self._ok_steps()}),
                encoding='utf-8',
            )

            with patch('gmgn_monitor.status.run_checks', return_value=[]):
                status = build_status(root, require_report=True)

        self.assertEqual(status['status'], 'fail')
        self.assertEqual(status['report_status'], 'ok')
        self.assertIsNone(status['report_age_minutes'])
        self.assertIsNone(status['report_future_seconds'])

    def test_build_status_with_report_requirement_fails_when_report_timestamp_is_future(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_report.json').write_text(
                json.dumps({
                    'status': 'ok',
                    'generated_at': '2026-07-01T12:05:00+00:00',
                    'steps': self._ok_steps(),
                }),
                encoding='utf-8',
            )

            with patch('gmgn_monitor.status.run_checks', return_value=[]):
                status = build_status(
                    root,
                    require_report=True,
                    now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                )

        self.assertEqual(status['status'], 'fail')
        self.assertEqual(status['report_age_minutes'], 0)
        self.assertEqual(status['report_future_seconds'], 300)

    def test_build_status_can_fail_on_future_report_timestamp(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_report.json').write_text(
                json.dumps({
                    'status': 'ok',
                    'generated_at': '2026-07-01T12:05:00+00:00',
                    'steps': self._ok_steps(),
                }),
                encoding='utf-8',
            )

            with patch('gmgn_monitor.status.run_checks', return_value=[]):
                status = build_status(
                    root,
                    fail_on_future_report=True,
                    now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                )

        self.assertEqual(status['status'], 'fail')
        self.assertEqual(status['report_future_seconds'], 300)
        self.assertTrue(status['fail_on_future_report'])

    def test_build_status_with_report_requirement_fails_when_report_steps_are_incomplete(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_report.json').write_text(
                json.dumps({
                    'status': 'ok',
                    'generated_at': '2026-07-01T12:00:00+00:00',
                    'steps': [{'name': 'pipeline', 'status': 'ok'}],
                }),
                encoding='utf-8',
            )

            with patch('gmgn_monitor.status.run_checks', return_value=[]):
                status = build_status(root, require_report=True)

        self.assertEqual(status['status'], 'fail')
        self.assertFalse(status['report_steps_complete'])

    def test_build_status_fails_when_doctor_fails(self):
        with TemporaryDirectory() as temp_dir:
            with patch('gmgn_monitor.status.run_checks', return_value=['bad']):
                status = build_status(Path(temp_dir))

        self.assertEqual(status['status'], 'fail')
        self.assertEqual(status['doctor_failures'], ['bad'])

    def test_build_status_reports_fresh_verification_lock_without_failing(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification.lock').write_text('fresh\n', encoding='utf-8')

            with patch('gmgn_monitor.status.run_checks', return_value=[]):
                status = build_status(root, fail_on_stale_lock=True)

        self.assertEqual(status['status'], 'ok')
        self.assertTrue(status['verification_lock']['exists'])
        self.assertFalse(status['verification_lock']['stale'])
        self.assertTrue(status['fail_on_stale_lock'])

    def test_build_status_can_fail_on_stale_verification_lock(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            lock_path = root / 'data/verification.lock'
            lock_path.write_text('stale\n', encoding='utf-8')
            old_time = time.time() - 7200
            os.utime(lock_path, (old_time, old_time))

            with patch('gmgn_monitor.status.run_checks', return_value=[]):
                status = build_status(root, fail_on_stale_lock=True)

        self.assertEqual(status['status'], 'fail')
        self.assertTrue(status['verification_lock']['exists'])
        self.assertTrue(status['verification_lock']['stale'])

    def test_build_status_reports_fresh_temp_artifact_without_failing(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/.verification_report.json.fresh.tmp').write_text('fresh\n', encoding='utf-8')

            with patch('gmgn_monitor.status.run_checks', return_value=[]):
                status = build_status(root, fail_on_stale_temp_artifacts=True)

        self.assertEqual(status['status'], 'ok')
        self.assertEqual(status['temp_artifacts']['count'], 1)
        self.assertEqual(status['temp_artifacts']['stale_count'], 0)
        self.assertTrue(status['fail_on_stale_temp_artifacts'])

    def test_build_status_can_fail_on_stale_temp_artifact(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            temp_path = root / 'data/.verification_report.json.stale.tmp'
            temp_path.write_text('stale\n', encoding='utf-8')
            old_time = time.time() - 7200
            os.utime(temp_path, (old_time, old_time))

            with patch('gmgn_monitor.status.run_checks', return_value=[]):
                status = build_status(root, fail_on_stale_temp_artifacts=True)

        self.assertEqual(status['status'], 'fail')
        self.assertEqual(status['temp_artifacts']['count'], 1)
        self.assertEqual(status['temp_artifacts']['stale_count'], 1)

    def test_build_status_fails_when_latest_history_failed(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_history.jsonl').write_text(
                json.dumps({'status': 'fail', 'generated_at': 'now'}) + '\n',
                encoding='utf-8',
            )

            with patch('gmgn_monitor.status.run_checks', return_value=[]):
                status = build_status(root)

        self.assertEqual(status['status'], 'fail')

    def test_build_status_applies_history_limit(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_history.jsonl').write_text(
                json.dumps({'status': 'fail', 'generated_at': 'old'}) + '\n' +
                json.dumps({'status': 'ok', 'generated_at': 'new'}) + '\n',
                encoding='utf-8',
            )

            with patch('gmgn_monitor.status.run_checks', return_value=[]):
                status = build_status(root, history_limit=1, fail_on_any_history_failure=True)

        self.assertEqual(status['status'], 'ok')
        self.assertEqual(status['history']['record_count'], 1)
        self.assertEqual(status['history']['last_generated_at'], 'new')

    def test_build_status_can_fail_on_any_selected_history_failure(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_history.jsonl').write_text(
                json.dumps({'status': 'fail', 'generated_at': 'old'}) + '\n' +
                json.dumps({'status': 'ok', 'generated_at': 'new'}) + '\n',
                encoding='utf-8',
            )

            with patch('gmgn_monitor.status.run_checks', return_value=[]):
                status = build_status(root, fail_on_any_history_failure=True)

        self.assertEqual(status['status'], 'fail')
        self.assertEqual(status['history']['failure_count'], 1)

    def test_build_status_can_fail_when_selected_history_steps_are_incomplete(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_history.jsonl').write_text(
                json.dumps({
                    'status': 'ok',
                    'generated_at': 'new',
                    'steps': [{'name': 'pipeline', 'status': 'ok'}],
                }) + '\n',
                encoding='utf-8',
            )

            with patch('gmgn_monitor.status.run_checks', return_value=[]):
                status = build_status(root, require_history_complete_steps=True)

        self.assertEqual(status['status'], 'fail')
        self.assertEqual(status['history']['incomplete_step_record_count'], 1)
        self.assertFalse(status['history']['last_record_steps_complete'])

    def test_build_status_with_history_step_requirement_passes_when_selected_history_is_complete(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_history.jsonl').write_text(
                json.dumps({
                    'status': 'fail',
                    'generated_at': 'old',
                    'steps': [{'name': 'pipeline', 'status': 'ok'}],
                }) + '\n' +
                json.dumps({
                    'status': 'ok',
                    'generated_at': 'new',
                    'steps': self._ok_steps(),
                }) + '\n',
                encoding='utf-8',
            )

            with patch('gmgn_monitor.status.run_checks', return_value=[]):
                status = build_status(root, history_limit=1, require_history_complete_steps=True)

        self.assertEqual(status['status'], 'ok')
        self.assertEqual(status['history']['record_count'], 1)
        self.assertEqual(status['history']['incomplete_step_record_count'], 0)
        self.assertTrue(status['history']['last_record_steps_complete'])

    def test_build_status_can_fail_when_selected_history_timestamp_is_invalid(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_history.jsonl').write_text(
                json.dumps({
                    'status': 'ok',
                    'generated_at': 'not-a-timestamp',
                    'steps': self._ok_steps(),
                }) + '\n',
                encoding='utf-8',
            )

            with patch('gmgn_monitor.status.run_checks', return_value=[]):
                status = build_status(root, require_history_valid_timestamps=True)

        self.assertEqual(status['status'], 'fail')
        self.assertEqual(status['history']['invalid_timestamp_count'], 1)
        self.assertFalse(status['history']['last_record_timestamp_valid'])

    def test_build_status_can_fail_when_selected_history_timestamp_is_out_of_order(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_history.jsonl').write_text(
                json.dumps({
                    'status': 'ok',
                    'generated_at': '2026-07-01T12:02:00+00:00',
                    'steps': self._ok_steps(),
                }) + '\n' +
                json.dumps({
                    'status': 'ok',
                    'generated_at': '2026-07-01T12:01:00+00:00',
                    'steps': self._ok_steps(),
                }) + '\n',
                encoding='utf-8',
            )

            with patch('gmgn_monitor.status.run_checks', return_value=[]):
                status = build_status(root, require_history_valid_timestamps=True)

        self.assertEqual(status['status'], 'fail')
        self.assertEqual(status['history']['out_of_order_timestamp_count'], 1)
        self.assertTrue(status['history']['last_record_timestamp_valid'])

    def test_build_status_can_fail_when_selected_history_timestamp_is_future(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_history.jsonl').write_text(
                json.dumps({
                    'status': 'ok',
                    'generated_at': '2026-07-01T12:05:00+00:00',
                    'steps': self._ok_steps(),
                }) + '\n',
                encoding='utf-8',
            )

            with patch('gmgn_monitor.status.run_checks', return_value=[]):
                status = build_status(
                    root,
                    require_history_valid_timestamps=True,
                    now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                )

        self.assertEqual(status['status'], 'fail')
        self.assertEqual(status['history']['future_timestamp_count'], 1)
        self.assertTrue(status['history']['last_record_timestamp_future'])

    def test_build_status_with_history_timestamp_requirement_passes_when_selected_history_is_valid(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_history.jsonl').write_text(
                json.dumps({
                    'status': 'ok',
                    'generated_at': 'not-a-timestamp',
                    'steps': self._ok_steps(),
                }) + '\n' +
                json.dumps({
                    'status': 'ok',
                    'generated_at': '2026-07-01T12:01:00+00:00',
                    'steps': self._ok_steps(),
                }) + '\n',
                encoding='utf-8',
            )

            with patch('gmgn_monitor.status.run_checks', return_value=[]):
                status = build_status(root, history_limit=1, require_history_valid_timestamps=True)

        self.assertEqual(status['status'], 'ok')
        self.assertEqual(status['history']['record_count'], 1)
        self.assertEqual(status['history']['invalid_timestamp_count'], 0)
        self.assertEqual(status['history']['out_of_order_timestamp_count'], 0)
        self.assertTrue(status['history']['last_record_timestamp_valid'])

    def test_report_matches_latest_history_returns_true_for_matching_record(self):
        report = {
            'artifact_fingerprints': {'data/pipeline/candidate_events.jsonl': 'abc'},
            'config_fingerprints': {'config/thresholds.json': 'def'},
            'generated_at': 'now',
            'operational_summary': {'candidate_count': 1},
            'status': 'ok',
            'steps': self._ok_steps(),
        }

        match = report_matches_latest_history(report, [report.copy()])

        self.assertTrue(match)

    def test_report_matches_latest_history_returns_false_for_stale_history(self):
        report = {
            'artifact_fingerprints': {'data/pipeline/candidate_events.jsonl': 'abc'},
            'config_fingerprints': {'config/thresholds.json': 'def'},
            'generated_at': 'new',
            'status': 'ok',
        }
        history = [{
            'artifact_fingerprints': {'data/pipeline/candidate_events.jsonl': 'abc'},
            'config_fingerprints': {'config/thresholds.json': 'def'},
            'generated_at': 'old',
            'status': 'ok',
        }]

        match = report_matches_latest_history(report, history)

        self.assertFalse(match)

    def test_report_matches_latest_history_returns_false_for_step_drift(self):
        report = {
            'artifact_fingerprints': {'data/pipeline/candidate_events.jsonl': 'abc'},
            'config_fingerprints': {'config/thresholds.json': 'def'},
            'generated_at': 'now',
            'operational_summary': {'candidate_count': 1},
            'status': 'ok',
            'steps': self._ok_steps(),
        }
        history = [report | {'steps': [{'name': 'pipeline', 'status': 'ok'}]}]

        match = report_matches_latest_history(report, history)

        self.assertFalse(match)

    def test_report_matches_latest_history_returns_false_for_operational_summary_drift(self):
        report = {
            'artifact_fingerprints': {'data/pipeline/candidate_events.jsonl': 'abc'},
            'config_fingerprints': {'config/thresholds.json': 'def'},
            'generated_at': 'now',
            'operational_summary': {'candidate_count': 1},
            'status': 'ok',
            'steps': self._ok_steps(),
        }
        history = [report | {'operational_summary': {'candidate_count': 0}}]

        match = report_matches_latest_history(report, history)

        self.assertFalse(match)

    def test_report_matches_latest_history_returns_none_without_evidence(self):
        self.assertIsNone(report_matches_latest_history(None, []))

    def test_report_has_required_steps_returns_true_when_all_required_steps_are_ok(self):
        report = {'steps': self._ok_steps()}

        self.assertTrue(report_has_required_steps(report))

    def test_report_has_required_steps_returns_false_when_required_step_failed(self):
        report = {'steps': self._ok_steps() + [{'name': 'tests', 'status': 'fail'}]}

        self.assertFalse(report_has_required_steps(report))

    def test_report_has_required_steps_returns_false_when_required_step_is_missing(self):
        report = {'steps': [{'name': 'pipeline', 'status': 'ok'}]}

        self.assertFalse(report_has_required_steps(report))

    def test_report_has_required_steps_returns_none_without_report(self):
        self.assertIsNone(report_has_required_steps(None))

    def test_build_status_with_history_current_requirement_passes_when_report_matches_latest_history(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report = {
                'artifact_fingerprints': {'data/pipeline/candidate_events.jsonl': 'abc'},
                'config_fingerprints': {'config/thresholds.json': 'def'},
                'generated_at': 'now',
                'status': 'ok',
                'steps': self._ok_steps(),
            }
            (root / 'data').mkdir()
            (root / 'data/verification_report.json').write_text(json.dumps(report), encoding='utf-8')
            (root / 'data/verification_history.jsonl').write_text(json.dumps(report) + '\n', encoding='utf-8')

            with patch('gmgn_monitor.status.run_checks', return_value=[]):
                status = build_status(root, require_history_current=True)

        self.assertEqual(status['status'], 'ok')
        self.assertTrue(status['report_matches_latest_history'])
        self.assertTrue(status['require_history_current'])

    def test_build_status_with_history_current_requirement_fails_when_history_is_stale(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_report.json').write_text(
                json.dumps({
                    'artifact_fingerprints': {'data/pipeline/candidate_events.jsonl': 'abc'},
                    'config_fingerprints': {'config/thresholds.json': 'def'},
                    'generated_at': 'new',
                    'status': 'ok',
                }),
                encoding='utf-8',
            )
            (root / 'data/verification_history.jsonl').write_text(
                json.dumps({
                    'artifact_fingerprints': {'data/pipeline/candidate_events.jsonl': 'abc'},
                    'config_fingerprints': {'config/thresholds.json': 'def'},
                    'generated_at': 'old',
                    'status': 'ok',
                }) + '\n',
                encoding='utf-8',
            )

            with patch('gmgn_monitor.status.run_checks', return_value=[]):
                status = build_status(root, require_history_current=True)

        self.assertEqual(status['status'], 'fail')
        self.assertFalse(status['report_matches_latest_history'])

    def test_build_status_with_history_current_requirement_fails_when_latest_history_steps_drift(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report = {
                'artifact_fingerprints': {'data/pipeline/candidate_events.jsonl': 'abc'},
                'config_fingerprints': {'config/thresholds.json': 'def'},
                'generated_at': 'now',
                'operational_summary': {'candidate_count': 1},
                'status': 'ok',
                'steps': self._ok_steps(),
            }
            history_record = report | {'steps': [{'name': 'pipeline', 'status': 'ok'}]}
            (root / 'data').mkdir()
            (root / 'data/verification_report.json').write_text(json.dumps(report), encoding='utf-8')
            (root / 'data/verification_history.jsonl').write_text(json.dumps(history_record) + '\n', encoding='utf-8')

            with patch('gmgn_monitor.status.run_checks', return_value=[]):
                status = build_status(root, require_history_current=True)

        self.assertEqual(status['status'], 'fail')
        self.assertFalse(status['report_matches_latest_history'])

    def test_build_status_with_history_current_requirement_fails_without_evidence(self):
        with TemporaryDirectory() as temp_dir:
            with patch('gmgn_monitor.status.run_checks', return_value=[]):
                status = build_status(Path(temp_dir), require_history_current=True)

        self.assertEqual(status['status'], 'fail')
        self.assertIsNone(status['report_matches_latest_history'])

    def test_format_status_outputs_summary(self):
        text = format_status({
            'doctor_failures': [],
            'fail_on_any_history_failure': True,
            'history': {
                'failure_count': 0,
                'future_timestamp_count': 0,
                'incomplete_step_record_count': 0,
                'invalid_timestamp_count': 0,
                'last_record_status_matches_steps': True,
                'last_record_timestamp_future': False,
                'last_record_timestamp_valid': True,
                'last_record_steps_complete': True,
                'last_status': 'ok',
                'out_of_order_timestamp_count': 0,
                'record_count': 1,
                'status_step_mismatch_count': 0,
            },
            'history_limit': 5,
            'max_report_age_minutes': 30,
            'report_age_minutes': 15,
            'report_future_seconds': 0,
            'report_generated_at': 'now',
            'report_matches_latest_history': True,
            'report_steps_complete': True,
            'report_status': 'ok',
            'require_history_complete_steps': True,
            'require_history_current': True,
            'require_history_valid_timestamps': True,
            'require_report': True,
            'status': 'ok',
            'fail_on_future_report': True,
            'fail_on_stale_lock': True,
            'fail_on_stale_temp_artifacts': True,
            'temp_artifacts': {
                'base_path': '/tmp/data',
                'count': 2,
                'files': [],
                'stale_count': 1,
            },
            'verification_lock': {
                'age_seconds': 12,
                'exists': True,
                'path': '/tmp/verification.lock',
                'stale': False,
            },
        })

        self.assertIn('Status: ok', text)
        self.assertIn('Report age minutes: 15', text)
        self.assertIn('Report future seconds: 0', text)
        self.assertIn('Report matches latest history: True', text)
        self.assertIn('Report steps complete: True', text)
        self.assertIn('Max report age minutes: 30', text)
        self.assertIn('Require report: True', text)
        self.assertIn('Fail on future report: True', text)
        self.assertIn('Require history complete steps: True', text)
        self.assertIn('Require history valid timestamps: True', text)
        self.assertIn('Require history current: True', text)
        self.assertIn('Verification lock present: True', text)
        self.assertIn('Verification lock stale: False', text)
        self.assertIn('Verification lock age seconds: 12', text)
        self.assertIn('Fail on stale lock: True', text)
        self.assertIn('Temp artifact count: 2', text)
        self.assertIn('Stale temp artifact count: 1', text)
        self.assertIn('Fail on stale temp artifacts: True', text)
        self.assertIn('History limit: 5', text)
        self.assertIn('Fail on any history failure: True', text)
        self.assertIn('History records: 1', text)
        self.assertIn('History incomplete step records: 0', text)
        self.assertIn('History status-step mismatch records: 0', text)
        self.assertIn('History invalid timestamp records: 0', text)
        self.assertIn('History future timestamp records: 0', text)
        self.assertIn('History out-of-order timestamp records: 0', text)
        self.assertIn('History last record status matches steps: True', text)
        self.assertIn('History last record steps complete: True', text)
        self.assertIn('History last record timestamp valid: True', text)
        self.assertIn('History last record timestamp future: False', text)


if __name__ == '__main__':
    unittest.main()
