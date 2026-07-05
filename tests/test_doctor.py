import unittest
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time

from gmgn_monitor.doctor import build_report, run_checks


class DoctorTest(unittest.TestCase):
    def _ok_steps(self):
        return [
            {'name': 'pipeline', 'status': 'ok'},
            {'name': 'expectations', 'status': 'ok'},
            {'name': 'doctor', 'status': 'ok'},
            {'name': 'tests', 'status': 'ok'},
            {'name': 'safety_scan', 'status': 'ok'},
        ]

    def _ok_operational_summary(self):
        return {
            'automation_gate_status': 'auto_trading_enabled',
            'candidate_count': 4,
            'decisions': {'alert': 1, 'reject': 2, 'watch': 1},
            'outcomes': {'pending': 2, 'reviewed': 2},
        }

    def _ok_generated_event(self):
        return {
            'blacklist_risk': False,
            'bundle_buy_percent': 4.0,
            'chain': 'solana',
            'decision': 'alert',
            'detected_at': '2026-07-01T14:00:00Z',
            'dev_holding_percent': 1.2,
            'freeze_renounced': True,
            'holder_count': 280,
            'honeypot_risk': False,
            'insider_or_rat_percent': 6.0,
            'liquidity': 140.0,
            'lp_burned_or_locked': True,
            'market_cap': 69000.0,
            'mint_renounced': True,
            'outcome': {'reviewed': False},
            'reasons': ['liquidity meets minimum'],
            'score': 100,
            'source': 'fixture:new_token',
            'symbol': 'GOOD',
            'tax_risk': False,
            'token_address': 'Good111111111111111111111111111111111111111',
            'top10_holder_percent': 18.0,
            'tx_count_1m': 85,
            'volume_1m': 220.0,
            'volume_5m': 1800.0,
        }

    def test_current_workspace_passes_doctor_checks(self):
        failures = run_checks(include_verification_artifacts=False)

        self.assertEqual(failures, [])

    def test_build_report_marks_ok_or_fail(self):
        self.assertEqual(build_report([]), {'status': 'ok', 'failures': []})
        self.assertEqual(build_report(['missing generated output: x'])['status'], 'fail')

    def test_pipeline_gate_must_stay_blocked(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data/pipeline').mkdir(parents=True)
            (root / 'data/pipeline/automation_gate.md').write_text('Status: ready\n', encoding='utf-8')

            failures = run_checks(root)

        self.assertIn('generated output missing required content: data/pipeline/automation_gate.md', failures)

    def test_required_generated_output_must_be_utf8(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data/pipeline').mkdir(parents=True)
            (root / 'data/pipeline/daily_summary.md').write_bytes(b'\xff')

            failures = run_checks(root)

        self.assertIn('invalid generated output UTF-8: data/pipeline/daily_summary.md: invalid start byte', failures)

    def test_required_generated_output_read_error_fails_doctor(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data/pipeline/daily_summary.md').mkdir(parents=True)

            failures = run_checks(root)

        self.assertTrue(any(
            failure.startswith('invalid generated output read: data/pipeline/daily_summary.md:')
            for failure in failures
        ))

    def test_missing_reviewed_outputs_fail_doctor(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data/pipeline').mkdir(parents=True)
            for path in (
                'candidate_events.jsonl',
                'daily_summary.md',
                'telegram_dry_run.txt',
                'trade_plans.json',
                'automation_gate.md',
            ):
                (root / f'data/pipeline/{path}').write_text('x\n', encoding='utf-8')

            failures = run_checks(root)

        self.assertIn('missing generated output: data/pipeline/reviewed_candidate_events.jsonl', failures)
        self.assertIn('missing generated output: data/pipeline/outcome_analysis.md', failures)

    def test_invalid_pipeline_jsonl_fails_doctor(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data/pipeline').mkdir(parents=True)
            (root / 'data/pipeline/candidate_events.jsonl').write_text('not-json\n', encoding='utf-8')

            failures = run_checks(root)

        self.assertTrue(any(failure.startswith('invalid generated JSONL: data/pipeline/candidate_events.jsonl line 1:') for failure in failures))

    def test_invalid_utf8_pipeline_jsonl_fails_doctor_without_traceback(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data/pipeline').mkdir(parents=True)
            (root / 'data/pipeline/candidate_events.jsonl').write_bytes(b'\xff')

            failures = run_checks(root)

        self.assertIn('invalid generated JSONL: data/pipeline/candidate_events.jsonl: invalid UTF-8: invalid start byte', failures)

    def test_invalid_generated_event_shape_fails_doctor(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            event = self._ok_generated_event()
            event['decision'] = 'buy'
            event['score'] = -1
            event['reasons'] = 'not-a-list'
            event['outcome'] = {}
            (root / 'data/pipeline').mkdir(parents=True)
            (root / 'data/pipeline/candidate_events.jsonl').write_text(json.dumps(event) + '\n', encoding='utf-8')

            failures = run_checks(root)

        self.assertIn('invalid generated event decision: data/pipeline/candidate_events.jsonl line 1', failures)
        self.assertIn('invalid generated event score: data/pipeline/candidate_events.jsonl line 1', failures)
        self.assertIn('invalid generated event reasons: data/pipeline/candidate_events.jsonl line 1', failures)
        self.assertIn('invalid generated event outcome: data/pipeline/candidate_events.jsonl line 1', failures)

    def test_invalid_generated_event_candidate_schema_fails_doctor(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            event = self._ok_generated_event()
            event.pop('token_address')
            (root / 'data/pipeline').mkdir(parents=True)
            (root / 'data/pipeline/reviewed_candidate_events.jsonl').write_text(json.dumps(event) + '\n', encoding='utf-8')

            failures = run_checks(root)

        self.assertIn(
            'invalid generated event candidate schema: data/pipeline/reviewed_candidate_events.jsonl line 1: missing field: token_address',
            failures,
        )

    def test_boolean_numeric_generated_event_values_fail_doctor(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            event = self._ok_generated_event()
            event['liquidity'] = True
            event['score'] = True
            (root / 'data/pipeline').mkdir(parents=True)
            (root / 'data/pipeline/candidate_events.jsonl').write_text(json.dumps(event) + '\n', encoding='utf-8')

            failures = run_checks(root)

        self.assertIn(
            'invalid generated event candidate schema: data/pipeline/candidate_events.jsonl line 1: liquidity must be numeric',
            failures,
        )
        self.assertIn('invalid generated event score: data/pipeline/candidate_events.jsonl line 1', failures)

    def test_invalid_trade_plans_json_fails_doctor(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data/pipeline').mkdir(parents=True)
            (root / 'data/pipeline/trade_plans.json').write_text('{"not": "a list"}\n', encoding='utf-8')

            failures = run_checks(root)

        self.assertIn('invalid trade plans JSON: expected list', failures)

    def test_malformed_trade_plans_json_fails_doctor_with_line_number(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data/pipeline').mkdir(parents=True)
            (root / 'data/pipeline/trade_plans.json').write_text('[\nnot-json\n', encoding='utf-8')

            failures = run_checks(root)

        self.assertIn('invalid trade plans JSON: line 2: Expecting value', failures)

    def test_invalid_utf8_trade_plans_json_fails_doctor_without_traceback(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data/pipeline').mkdir(parents=True)
            (root / 'data/pipeline/trade_plans.json').write_bytes(b'\xff')

            failures = run_checks(root)

        self.assertIn('invalid trade plans JSON: invalid UTF-8: invalid start byte', failures)

    def test_trade_plans_json_read_error_fails_doctor_without_traceback(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data/pipeline/trade_plans.json').mkdir(parents=True)

            failures = run_checks(root)

        self.assertTrue(any(
            failure.startswith('invalid trade plans JSON: read failed:')
            for failure in failures
        ))

    def test_generated_jsonl_read_error_fails_doctor_without_traceback(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data/pipeline/candidate_events.jsonl').mkdir(parents=True)

            failures = run_checks(root)

        self.assertTrue(any(
            failure.startswith('invalid generated JSONL: data/pipeline/candidate_events.jsonl: read failed:')
            for failure in failures
        ))

    def test_invalid_verification_expectations_config_fails_doctor(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'config').mkdir()
            for name in ('thresholds.json', 'risk_limits.json', 'automation_gate.json'):
                (root / f'config/{name}').write_text(Path(f'config/{name}').read_text(encoding='utf-8'), encoding='utf-8')
            (root / 'config/verification_expectations.json').write_text(
                '{"automation_gate_status": 1, "candidate_count": "4", "decisions": {}, "outcomes": {}}',
                encoding='utf-8',
            )

            failures = run_checks(root)

        self.assertTrue(any(failure.startswith('invalid verification expectations config:') for failure in failures))

    def test_invalid_utf8_verification_expectations_config_fails_doctor(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'config').mkdir()
            for name in ('thresholds.json', 'risk_limits.json', 'automation_gate.json'):
                (root / f'config/{name}').write_text(Path(f'config/{name}').read_text(encoding='utf-8'), encoding='utf-8')
            (root / 'config/verification_expectations.json').write_bytes(b'\xff')

            failures = run_checks(root)

        self.assertTrue(any(failure.startswith('invalid verification expectations config:') for failure in failures))
        self.assertTrue(any('invalid verification expectations UTF-8:' in failure for failure in failures))

    def test_invalid_verification_report_fails_doctor_when_present(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_report.json').write_text('{"status": "maybe", "steps": []}', encoding='utf-8')

            failures = run_checks(root)

        self.assertIn('invalid verification report status', failures)

    def test_malformed_verification_report_json_fails_doctor(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_report.json').write_text('not-json\n', encoding='utf-8')

            failures = run_checks(root)

        self.assertTrue(any(failure.startswith('invalid verification report: invalid verification report JSON:') for failure in failures))

    def test_invalid_utf8_verification_report_fails_doctor(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_report.json').write_bytes(b'\xff')

            failures = run_checks(root)

        self.assertTrue(any(failure.startswith('invalid verification report: invalid verification report UTF-8:') for failure in failures))

    def test_non_object_verification_report_fails_doctor(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_report.json').write_text('[]\n', encoding='utf-8')

            failures = run_checks(root)

        self.assertIn('invalid verification report: invalid verification report: expected object', failures)

    def test_incomplete_verification_report_steps_fail_doctor_when_present(self):
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

            failures = run_checks(root)

        self.assertIn('incomplete verification report steps', failures)

    def test_verification_report_status_step_mismatch_fails_doctor_when_present(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_report.json').write_text(
                json.dumps({
                    'artifact_fingerprints': {},
                    'config_fingerprints': {},
                    'operational_summary': self._ok_operational_summary(),
                    'status': 'fail',
                    'generated_at': '2026-07-01T12:00:00+00:00',
                    'steps': self._ok_steps(),
                }),
                encoding='utf-8',
            )

            failures = run_checks(root)

        self.assertIn('verification report status mismatch with steps', failures)

    def test_invalid_verification_report_timestamp_fails_doctor_when_present(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_report.json').write_text(
                json.dumps({
                    'status': 'ok',
                    'generated_at': 'not-a-timestamp',
                    'steps': self._ok_steps(),
                }),
                encoding='utf-8',
            )

            failures = run_checks(root)

        self.assertIn('invalid verification report timestamp', failures)

    def test_missing_verification_report_operational_summary_fails_doctor_when_present(self):
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

            failures = run_checks(root)

        self.assertIn('invalid verification report operational summary', failures)

    def test_drifted_verification_report_operational_summary_fails_doctor_when_present(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'config').mkdir()
            (root / 'config/verification_expectations.json').write_text(
                Path('config/verification_expectations.json').read_text(encoding='utf-8'),
                encoding='utf-8',
            )
            summary = self._ok_operational_summary()
            summary['candidate_count'] = 3
            (root / 'data/verification_report.json').write_text(
                json.dumps({
                    'operational_summary': summary,
                    'status': 'ok',
                    'generated_at': '2026-07-01T12:00:00+00:00',
                    'steps': self._ok_steps(),
                }),
                encoding='utf-8',
            )

            failures = run_checks(root)

        self.assertIn(
            'verification report operational summary mismatch: candidate_count expected 4, got 3',
            failures,
        )

    def test_stale_verification_report_config_fingerprint_fails_doctor(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'config').mkdir()
            (root / 'config/thresholds.json').write_text('{}\n', encoding='utf-8')
            (root / 'data/verification_report.json').write_text(
                '{"status": "ok", "steps": [], "config_fingerprints": {"config/thresholds.json": "stale"}}',
                encoding='utf-8',
            )

            failures = run_checks(root)

        self.assertIn('verification report config fingerprint mismatch: config/thresholds.json', failures)

    def test_missing_verification_report_fingerprint_objects_fail_doctor(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_report.json').write_text(
                json.dumps({
                    'operational_summary': self._ok_operational_summary(),
                    'status': 'ok',
                    'generated_at': '2026-07-01T12:00:00+00:00',
                    'steps': self._ok_steps(),
                }),
                encoding='utf-8',
            )

            failures = run_checks(root)

        self.assertIn('verification report config fingerprint mismatch: expected object', failures)
        self.assertIn('verification report artifact fingerprint mismatch: expected object', failures)

    def test_missing_verification_report_config_fingerprint_file_fails_doctor(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'config').mkdir()
            (root / 'data').mkdir()
            (root / 'config/thresholds.json').write_text('{}\n', encoding='utf-8')
            (root / 'data/verification_report.json').write_text(
                json.dumps({
                    'artifact_fingerprints': {},
                    'config_fingerprints': {},
                    'operational_summary': self._ok_operational_summary(),
                    'status': 'ok',
                    'generated_at': '2026-07-01T12:00:00+00:00',
                    'steps': self._ok_steps(),
                }),
                encoding='utf-8',
            )

            failures = run_checks(root)

        self.assertIn(
            'verification report config fingerprint mismatch: missing reported file config/thresholds.json',
            failures,
        )

    def test_stale_verification_report_artifact_fingerprint_fails_doctor(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data/pipeline').mkdir(parents=True)
            (root / 'data/pipeline/daily_summary.md').write_text('summary\n', encoding='utf-8')
            (root / 'data/verification_report.json').write_text(
                '{"status": "ok", "steps": [], "artifact_fingerprints": {"data/pipeline/daily_summary.md": "stale"}}',
                encoding='utf-8',
            )

            failures = run_checks(root)

        self.assertIn('verification report artifact fingerprint mismatch: data/pipeline/daily_summary.md', failures)

    def test_invalid_verification_history_fails_doctor_when_present(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_history.jsonl').write_text('{"status": "maybe"}\n', encoding='utf-8')

            failures = run_checks(root)

        self.assertIn('invalid verification history status at line 1', failures)

    def test_malformed_verification_history_json_fails_doctor_with_line_number(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_history.jsonl').write_text('not-json\n', encoding='utf-8')

            failures = run_checks(root)

        self.assertTrue(any('invalid verification history:' in failure and 'invalid history JSON:' in failure for failure in failures))

    def test_non_object_verification_history_record_fails_doctor_with_line_number(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_history.jsonl').write_text('[]\n', encoding='utf-8')

            failures = run_checks(root)

        self.assertTrue(any('invalid verification history:' in failure and 'invalid history record: expected object' in failure for failure in failures))

    def test_incomplete_verification_history_steps_fail_doctor_when_present(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_history.jsonl').write_text(
                json.dumps({
                    'status': 'ok',
                    'generated_at': '2026-07-01T12:00:00+00:00',
                    'steps': [{'name': 'pipeline', 'status': 'ok'}],
                }) + '\n',
                encoding='utf-8',
            )

            failures = run_checks(root)

        self.assertIn('incomplete verification history steps at line 1', failures)

    def test_invalid_verification_history_timestamp_fails_doctor_when_present(self):
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

            failures = run_checks(root)

        self.assertIn('invalid verification history timestamp at line 1', failures)

    def test_out_of_order_verification_history_timestamp_fails_doctor_when_present(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_history.jsonl').write_text(
                json.dumps({
                    'status': 'ok',
                    'generated_at': '2026-07-01T12:01:00+00:00',
                    'steps': self._ok_steps(),
                }) + '\n' +
                json.dumps({
                    'status': 'ok',
                    'generated_at': '2026-07-01T12:00:00+00:00',
                    'steps': self._ok_steps(),
                }) + '\n',
                encoding='utf-8',
            )

            failures = run_checks(root)

        self.assertIn('out-of-order verification history timestamp at line 2', failures)

    def test_future_verification_history_timestamp_fails_doctor_when_present(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification_history.jsonl').write_text(
                json.dumps({
                    'status': 'ok',
                    'generated_at': '2999-01-01T00:00:00+00:00',
                    'steps': self._ok_steps(),
                }) + '\n',
                encoding='utf-8',
            )

            failures = run_checks(root)

        self.assertIn('future verification history timestamp at line 1', failures)

    def test_drifted_verification_history_operational_summary_fails_doctor_when_present(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'config').mkdir()
            (root / 'config/verification_expectations.json').write_text(
                Path('config/verification_expectations.json').read_text(encoding='utf-8'),
                encoding='utf-8',
            )
            summary = self._ok_operational_summary()
            summary['candidate_count'] = 3
            (root / 'data/verification_history.jsonl').write_text(
                json.dumps({
                    'status': 'ok',
                    'generated_at': '2026-07-01T12:00:00+00:00',
                    'operational_summary': summary,
                    'steps': self._ok_steps(),
                }) + '\n',
                encoding='utf-8',
            )

            failures = run_checks(root)

        self.assertIn(
            'verification history operational summary mismatch at line 1: candidate_count expected 4, got 3',
            failures,
        )

    def test_verification_report_history_mismatch_fails_doctor_when_both_are_present(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report = {
                'artifact_fingerprints': {},
                'config_fingerprints': {},
                'generated_at': '2026-07-01T12:00:00+00:00',
                'operational_summary': self._ok_operational_summary(),
                'status': 'ok',
                'steps': self._ok_steps(),
            }
            history_record = report | {'generated_at': '2026-07-01T11:59:00+00:00'}
            (root / 'data').mkdir()
            (root / 'data/verification_report.json').write_text(json.dumps(report), encoding='utf-8')
            (root / 'data/verification_history.jsonl').write_text(json.dumps(history_record) + '\n', encoding='utf-8')

            failures = run_checks(root)

        self.assertIn('verification report does not match latest history record', failures)

    def test_fresh_verification_lock_does_not_fail_doctor(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification.lock').write_text('fresh\n', encoding='utf-8')

            failures = run_checks(root)

        self.assertFalse(any(failure.startswith('stale verification lock:') for failure in failures))

    def test_stale_verification_lock_fails_doctor(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            lock_path = root / 'data/verification.lock'
            lock_path.write_text('stale\n', encoding='utf-8')
            old_time = time.time() - 7200
            os.utime(lock_path, (old_time, old_time))

            failures = run_checks(root)

        self.assertTrue(any(failure.startswith('stale verification lock: data/verification.lock') for failure in failures))

    def test_fresh_temp_artifact_does_not_fail_doctor(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data/pipeline').mkdir(parents=True)
            (root / 'data/pipeline/.daily_summary.md.fresh.tmp').write_text('fresh\n', encoding='utf-8')

            failures = run_checks(root)

        self.assertFalse(any(failure.startswith('stale temp artifact:') for failure in failures))

    def test_stale_temp_artifact_fails_doctor(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data/pipeline').mkdir(parents=True)
            temp_path = root / 'data/pipeline/.daily_summary.md.stale.tmp'
            temp_path.write_text('stale\n', encoding='utf-8')
            old_time = time.time() - 7200
            os.utime(temp_path, (old_time, old_time))

            failures = run_checks(root)

        self.assertTrue(any(failure.startswith('stale temp artifact: data/pipeline/.daily_summary.md.stale.tmp') for failure in failures))


if __name__ == '__main__':
    unittest.main()
