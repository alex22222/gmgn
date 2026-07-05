import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from gmgn_monitor.history import (
    build_history_summary,
    check_history_integrity,
    format_history_summary,
    load_history,
    parse_generated_at,
    select_recent_records,
    should_fail_summary,
)


class HistoryTest(unittest.TestCase):
    def _ok_steps(self):
        return [
            {'name': 'pipeline', 'status': 'ok'},
            {'name': 'expectations', 'status': 'ok'},
            {'name': 'doctor', 'status': 'ok'},
            {'name': 'tests', 'status': 'ok'},
            {'name': 'safety_scan', 'status': 'ok'},
        ]

    def test_load_history_reads_jsonl_records(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'history.jsonl'
            path.write_text(
                json.dumps({'status': 'ok'}) + '\n' + json.dumps({'status': 'fail'}) + '\n',
                encoding='utf-8',
            )

            records = load_history(path)

        self.assertEqual([record['status'] for record in records], ['ok', 'fail'])

    def test_load_history_rejects_invalid_json_with_line_number(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'history.jsonl'
            path.write_text('{"status": "ok"}\nnot-json\n', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, r'history\.jsonl:2: invalid history JSON:'):
                load_history(path)

    def test_load_history_rejects_non_object_record_with_line_number(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'history.jsonl'
            path.write_text('[]\n', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, r'history\.jsonl:1: invalid history record: expected object'):
                load_history(path)

    def test_load_history_rejects_invalid_utf8(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'history.jsonl'
            path.write_bytes(b'\xff')

            with self.assertRaisesRegex(ValueError, r'history\.jsonl: invalid history UTF-8:'):
                load_history(path)

    def test_load_history_rejects_read_error(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'history.jsonl'
            path.mkdir()

            with self.assertRaisesRegex(ValueError, r'history\.jsonl: invalid history read:'):
                load_history(path)

    def test_build_history_summary_handles_empty_history(self):
        summary = build_history_summary([])

        self.assertEqual(summary['record_count'], 0)
        self.assertEqual(summary['failure_count'], 0)
        self.assertEqual(summary['consecutive_failure_count'], 0)
        self.assertEqual(summary['future_timestamp_count'], 0)
        self.assertEqual(summary['incomplete_step_record_count'], 0)
        self.assertEqual(summary['invalid_timestamp_count'], 0)
        self.assertEqual(summary['status_step_mismatch_count'], 0)
        self.assertIsNone(summary['last_record_status_matches_steps'])
        self.assertEqual(summary['out_of_order_timestamp_count'], 0)
        self.assertIsNone(summary['last_record_timestamp_future'])
        self.assertIsNone(summary['last_record_steps_complete'])
        self.assertIsNone(summary['last_record_timestamp_valid'])
        self.assertIsNone(summary['last_status'])
        self.assertIsNone(summary['last_success_generated_at'])

    def test_select_recent_records_limits_without_mutating_history(self):
        records = [
            {'status': 'ok', 'generated_at': 'one'},
            {'status': 'fail', 'generated_at': 'two'},
            {'status': 'ok', 'generated_at': 'three'},
        ]

        selected = select_recent_records(records, 2)

        self.assertEqual([record['generated_at'] for record in selected], ['two', 'three'])
        self.assertEqual(len(records), 3)

    def test_select_recent_records_rejects_non_positive_limit(self):
        with self.assertRaisesRegex(ValueError, 'history limit must be positive'):
            select_recent_records([], 0)

    def test_parse_generated_at_accepts_iso_timestamp(self):
        timestamp = parse_generated_at('2026-07-01T12:00:00+00:00')

        self.assertIsNotNone(timestamp)

    def test_parse_generated_at_rejects_non_iso_timestamp(self):
        self.assertIsNone(parse_generated_at('not-a-timestamp'))

    def test_build_history_summary_uses_latest_record(self):
        records = [
            {
                'status': 'fail',
                'generated_at': '2026-07-01T12:00:00+00:00',
                'steps': [{'name': 'tests', 'status': 'fail'}],
            },
            {
                'status': 'fail',
                'generated_at': '2026-07-01T12:01:00+00:00',
                'steps': [{'name': 'doctor', 'status': 'fail'}],
            },
            {
                'status': 'ok',
                'generated_at': '2026-07-01T12:02:00+00:00',
                'operational_summary': {'automation_gate_status': 'auto_trading_enabled', 'candidate_count': 4},
                'steps': self._ok_steps(),
            },
        ]

        summary = build_history_summary(records)

        self.assertEqual(summary['record_count'], 3)
        self.assertEqual(summary['failure_count'], 2)
        self.assertEqual(summary['last_generated_at'], '2026-07-01T12:02:00+00:00')
        self.assertEqual(summary['last_status'], 'ok')
        self.assertEqual(summary['last_success_generated_at'], '2026-07-01T12:02:00+00:00')
        self.assertEqual(summary['consecutive_failure_count'], 0)
        self.assertEqual(summary['incomplete_step_record_count'], 2)
        self.assertEqual(summary['future_timestamp_count'], 0)
        self.assertEqual(summary['invalid_timestamp_count'], 0)
        self.assertEqual(summary['status_step_mismatch_count'], 0)
        self.assertEqual(summary['out_of_order_timestamp_count'], 0)
        self.assertTrue(summary['last_record_status_matches_steps'])
        self.assertFalse(summary['last_record_timestamp_future'])
        self.assertTrue(summary['last_record_steps_complete'])
        self.assertTrue(summary['last_record_timestamp_valid'])
        self.assertEqual(summary['last_step_statuses'], {
            'pipeline': 'ok',
            'expectations': 'ok',
            'doctor': 'ok',
            'tests': 'ok',
            'safety_scan': 'ok',
        })
        self.assertEqual(summary['status_counts'], {'fail': 2, 'ok': 1})
        self.assertEqual(summary['step_failure_counts'], {'tests': 1, 'doctor': 1})

    def test_build_history_summary_counts_incomplete_step_records(self):
        records = [
            {'status': 'ok', 'generated_at': 'one', 'steps': self._ok_steps()},
            {'status': 'ok', 'generated_at': 'two', 'steps': [{'name': 'pipeline', 'status': 'ok'}]},
        ]

        summary = build_history_summary(records)

        self.assertEqual(summary['incomplete_step_record_count'], 1)
        self.assertFalse(summary['last_record_steps_complete'])
        self.assertFalse(summary['last_record_status_matches_steps'])

    def test_build_history_summary_counts_status_step_mismatches(self):
        records = [
            {'status': 'fail', 'generated_at': '2026-07-01T12:00:00+00:00', 'steps': self._ok_steps()},
            {'status': 'ok', 'generated_at': '2026-07-01T12:01:00+00:00', 'steps': [{'name': 'pipeline', 'status': 'fail'}]},
        ]

        summary = build_history_summary(records)

        self.assertEqual(summary['status_step_mismatch_count'], 2)
        self.assertFalse(summary['last_record_status_matches_steps'])

    def test_build_history_summary_counts_invalid_and_out_of_order_timestamps(self):
        records = [
            {'status': 'ok', 'generated_at': '2026-07-01T12:02:00+00:00', 'steps': self._ok_steps()},
            {'status': 'ok', 'generated_at': 'not-a-timestamp', 'steps': self._ok_steps()},
            {'status': 'ok', 'generated_at': '2026-07-01T12:01:00+00:00', 'steps': self._ok_steps()},
        ]

        summary = build_history_summary(records)

        self.assertEqual(summary['invalid_timestamp_count'], 1)
        self.assertEqual(summary['out_of_order_timestamp_count'], 1)
        self.assertTrue(summary['last_record_timestamp_valid'])

    def test_build_history_summary_counts_future_timestamps(self):
        records = [
            {'status': 'ok', 'generated_at': '2026-07-01T12:00:00+00:00', 'steps': self._ok_steps()},
            {'status': 'ok', 'generated_at': '2026-07-01T12:05:00+00:00', 'steps': self._ok_steps()},
        ]

        summary = build_history_summary(records, now=datetime(2026, 7, 1, 12, 1, tzinfo=timezone.utc))

        self.assertEqual(summary['future_timestamp_count'], 1)
        self.assertTrue(summary['last_record_timestamp_future'])

    def test_build_history_summary_counts_tail_failures(self):
        records = [
            {'status': 'ok', 'generated_at': 'one'},
            {'status': 'fail', 'generated_at': 'two'},
            {'status': 'fail', 'generated_at': 'three'},
        ]

        summary = build_history_summary(records)

        self.assertEqual(summary['consecutive_failure_count'], 2)
        self.assertEqual(summary['last_success_generated_at'], 'one')

    def test_format_history_summary_outputs_status_and_steps(self):
        text = format_history_summary({
            'consecutive_failure_count': 0,
            'failure_count': 0,
            'future_timestamp_count': 0,
            'incomplete_step_record_count': 0,
            'invalid_timestamp_count': 0,
            'last_record_status_matches_steps': True,
            'last_record_timestamp_future': False,
            'last_record_steps_complete': True,
            'last_record_timestamp_valid': True,
            'last_generated_at': 'now',
            'last_operational_summary': {'automation_gate_status': 'auto_trading_enabled', 'candidate_count': 4},
            'last_status': 'ok',
            'last_success_generated_at': 'now',
            'last_step_statuses': {'pipeline': 'ok'},
            'out_of_order_timestamp_count': 0,
            'record_count': 1,
            'status_counts': {'ok': 1},
            'status_step_mismatch_count': 0,
            'step_failure_counts': {'tests': 1},
        })

        self.assertIn('Records: 1', text)
        self.assertIn('Incomplete step records: 0', text)
        self.assertIn('Invalid timestamp records: 0', text)
        self.assertIn('Status-step mismatch records: 0', text)
        self.assertIn('Future timestamp records: 0', text)
        self.assertIn('Out-of-order timestamp records: 0', text)
        self.assertIn('Consecutive failures: 0', text)
        self.assertIn("Status counts: {'ok': 1}", text)
        self.assertIn('Last status: ok', text)
        self.assertIn('Last record status matches steps: True', text)
        self.assertIn('Last record steps complete: True', text)
        self.assertIn('Last record timestamp valid: True', text)
        self.assertIn('Last record timestamp future: False', text)
        self.assertIn('Last success generated at: now', text)
        self.assertIn('- tests: 1', text)
        self.assertIn('- pipeline: ok', text)

    def test_should_fail_summary_defaults_to_latest_status(self):
        summary = {'failure_count': 1, 'last_status': 'ok'}

        self.assertFalse(should_fail_summary(summary))

    def test_should_fail_summary_can_fail_on_any_failure(self):
        summary = {'failure_count': 1, 'last_status': 'ok'}

        self.assertTrue(should_fail_summary(summary, fail_on_any_failure=True))

    def test_should_fail_summary_can_fail_on_incomplete_steps(self):
        summary = {'failure_count': 0, 'incomplete_step_record_count': 1, 'last_status': 'ok'}

        self.assertTrue(should_fail_summary(summary, require_complete_steps=True))

    def test_should_fail_summary_can_fail_on_status_step_mismatch(self):
        summary = {
            'failure_count': 0,
            'incomplete_step_record_count': 0,
            'last_status': 'ok',
            'status_step_mismatch_count': 1,
        }

        self.assertTrue(should_fail_summary(summary, require_complete_steps=True))

    def test_should_fail_summary_can_fail_on_invalid_timestamps(self):
        summary = {
            'failure_count': 0,
            'invalid_timestamp_count': 1,
            'last_status': 'ok',
            'out_of_order_timestamp_count': 0,
        }

        self.assertTrue(should_fail_summary(summary, require_valid_timestamps=True))

    def test_should_fail_summary_can_fail_on_out_of_order_timestamps(self):
        summary = {
            'failure_count': 0,
            'invalid_timestamp_count': 0,
            'last_status': 'ok',
            'out_of_order_timestamp_count': 1,
        }

        self.assertTrue(should_fail_summary(summary, require_valid_timestamps=True))

    def test_should_fail_summary_can_fail_on_future_timestamps(self):
        summary = {
            'failure_count': 0,
            'future_timestamp_count': 1,
            'invalid_timestamp_count': 0,
            'last_status': 'ok',
            'out_of_order_timestamp_count': 0,
        }

        self.assertTrue(should_fail_summary(summary, require_valid_timestamps=True))

    def test_should_fail_summary_fails_when_latest_failed(self):
        summary = {'failure_count': 1, 'last_status': 'fail'}

        self.assertTrue(should_fail_summary(summary))

    def test_check_history_integrity_accepts_valid_records(self):
        failures = check_history_integrity([
            {'status': 'ok', 'generated_at': '2026-07-01T12:00:00+00:00', 'steps': self._ok_steps()},
            {'status': 'ok', 'generated_at': '2026-07-01T12:01:00+00:00', 'steps': self._ok_steps()},
        ])

        self.assertEqual(failures, [])

    def test_check_history_integrity_reports_invalid_records(self):
        failures = check_history_integrity([
            {'status': 'maybe', 'generated_at': '2026-07-01T12:02:00+00:00', 'steps': self._ok_steps()},
            {'status': 'ok', 'generated_at': 'not-a-timestamp', 'steps': [{'name': 'pipeline', 'status': 'ok'}]},
            {'status': 'ok', 'generated_at': '2026-07-01T12:01:00+00:00', 'steps': self._ok_steps()},
        ])

        self.assertEqual(failures, [
            'invalid verification history status at line 1',
            'incomplete verification history steps at line 2',
            'verification history status mismatch with steps at line 2',
            'invalid verification history timestamp at line 2',
            'out-of-order verification history timestamp at line 3',
        ])

    def test_check_history_integrity_reports_status_step_mismatch(self):
        failures = check_history_integrity([
            {'status': 'fail', 'generated_at': '2026-07-01T12:00:00+00:00', 'steps': self._ok_steps()},
        ])

        self.assertEqual(failures, ['verification history status mismatch with steps at line 1'])

    def test_check_history_integrity_reports_future_timestamp(self):
        failures = check_history_integrity([
            {'status': 'ok', 'generated_at': '2026-07-01T12:05:00+00:00', 'steps': self._ok_steps()},
        ], now=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc))

        self.assertEqual(failures, ['future verification history timestamp at line 1'])

    def test_check_history_integrity_accepts_matching_operational_summaries(self):
        summary = {
            'automation_gate_status': 'auto_trading_enabled',
            'candidate_count': 4,
            'decisions': {'alert': 1, 'reject': 2, 'watch': 1},
            'outcomes': {'pending': 2, 'reviewed': 2},
        }
        failures = check_history_integrity([
            {
                'status': 'ok',
                'generated_at': '2026-07-01T12:00:00+00:00',
                'operational_summary': summary,
                'steps': self._ok_steps(),
            },
        ], summary)

        self.assertEqual(failures, [])

    def test_check_history_integrity_reports_missing_and_drifted_operational_summaries(self):
        expected = {
            'automation_gate_status': 'auto_trading_enabled',
            'candidate_count': 4,
            'decisions': {'alert': 1, 'reject': 2, 'watch': 1},
            'outcomes': {'pending': 2, 'reviewed': 2},
        }
        drifted = dict(expected)
        drifted['candidate_count'] = 3

        failures = check_history_integrity([
            {
                'status': 'ok',
                'generated_at': '2026-07-01T12:00:00+00:00',
                'steps': self._ok_steps(),
            },
            {
                'status': 'ok',
                'generated_at': '2026-07-01T12:01:00+00:00',
                'operational_summary': drifted,
                'steps': self._ok_steps(),
            },
        ], expected)

        self.assertEqual(failures, [
            'invalid verification history operational summary at line 1',
            'verification history operational summary mismatch at line 2: candidate_count expected 4, got 3',
        ])


if __name__ == '__main__':
    unittest.main()
