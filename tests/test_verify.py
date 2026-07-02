import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from gmgn_monitor.verify import (
    VerificationStep,
    append_history,
    build_operational_summary,
    build_report,
    main,
    write_report,
)
from gmgn_monitor.fingerprints import build_artifact_fingerprints, build_config_fingerprints
from gmgn_monitor.verification_expectations import (
    check_operational_expectations,
    load_verification_expectations,
    validate_verification_expectations,
)
from gmgn_monitor.verification_steps import report_status_matches_steps


class VerifyTest(unittest.TestCase):
    def test_build_report_marks_all_steps_ok(self):
        report = build_report([
            VerificationStep('pipeline', True, ['data/pipeline/candidate_events.jsonl']),
            VerificationStep('doctor', True, []),
        ])

        self.assertEqual(report['status'], 'ok')
        self.assertIn('generated_at', report)
        self.assertEqual(report['steps'][0]['status'], 'ok')

    def test_build_report_marks_any_step_failure(self):
        report = build_report([
            VerificationStep('pipeline', True, []),
            VerificationStep('tests', False, ['failed']),
        ])

        self.assertEqual(report['status'], 'fail')
        self.assertEqual(report['steps'][1]['details'], ['failed'])

    def test_report_status_matches_steps_detects_consistency(self):
        self.assertTrue(report_status_matches_steps(build_report([
            VerificationStep('pipeline', True, []),
            VerificationStep('expectations', True, []),
            VerificationStep('doctor', True, []),
            VerificationStep('tests', True, []),
            VerificationStep('safety_scan', True, []),
        ])))
        self.assertFalse(report_status_matches_steps({
            'status': 'fail',
            'steps': [
                {'name': 'pipeline', 'status': 'ok'},
                {'name': 'expectations', 'status': 'ok'},
                {'name': 'doctor', 'status': 'ok'},
                {'name': 'tests', 'status': 'ok'},
                {'name': 'safety_scan', 'status': 'ok'},
            ],
        }))

    def test_write_report_creates_json_file(self):
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / 'reports/verification.json'
            report = build_report([VerificationStep('doctor', True, [])])

            write_report(report, output_path)

            saved = json.loads(output_path.read_text(encoding='utf-8'))
            temp_files = list((Path(temp_dir) / 'reports').glob('.verification.json.*.tmp'))

        self.assertEqual(saved['status'], 'ok')
        self.assertEqual(saved['steps'][0]['name'], 'doctor')
        self.assertEqual(temp_files, [])

    def test_append_history_writes_jsonl_records(self):
        with TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / 'reports/history.jsonl'
            append_history({'status': 'ok', 'generated_at': 'one'}, output_path)
            append_history({'status': 'fail', 'generated_at': 'two'}, output_path)

            records = [
                json.loads(line)
                for line in output_path.read_text(encoding='utf-8').splitlines()
            ]

        self.assertEqual([record['status'] for record in records], ['ok', 'fail'])
        self.assertEqual([record['generated_at'] for record in records], ['one', 'two'])

    def test_main_fails_when_verification_lock_is_active(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification.lock').write_text('active\n', encoding='utf-8')

            with patch('sys.argv', ['verify', '--root', str(root)]):
                with redirect_stdout(io.StringIO()):
                    code = main()

        self.assertEqual(code, 1)

    def test_main_reports_active_verification_lock_as_json_when_requested(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data').mkdir()
            (root / 'data/verification.lock').write_text('active\n', encoding='utf-8')

            stdout = io.StringIO()
            with patch('sys.argv', ['verify', '--root', str(root), '--json']):
                with redirect_stdout(stdout):
                    code = main()

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(payload['status'], 'fail')
        self.assertIn('lock already held:', payload['error'])

    def test_main_reports_report_write_error_without_traceback(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report_path = root / 'data/verification_report.json'
            report_path.mkdir(parents=True)

            stdout = io.StringIO()
            with patch('sys.argv', ['verify', '--root', str(root), '--report', str(report_path)]):
                with patch('gmgn_monitor.verify.run_verification', return_value=[VerificationStep('doctor', True, [])]):
                    with patch('gmgn_monitor.verify.build_config_fingerprints', return_value={}):
                        with patch('gmgn_monitor.verify.build_artifact_fingerprints', return_value={}):
                            with patch('gmgn_monitor.verify.build_operational_summary', return_value={}):
                                with redirect_stdout(stdout):
                                    code = main()

        self.assertEqual(code, 1)
        self.assertIn('GMGN monitor verification:', stdout.getvalue())
        self.assertIn('Is a directory', stdout.getvalue())
        self.assertNotIn('Traceback', stdout.getvalue())

    def test_main_reports_validation_error_as_json_without_traceback(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            stdout = io.StringIO()
            with patch('sys.argv', ['verify', '--root', str(root), '--json']):
                with patch('gmgn_monitor.verify.run_verification', return_value=[VerificationStep('doctor', True, [])]):
                    with patch('gmgn_monitor.verify.build_config_fingerprints', side_effect=ValueError('bad config')):
                        with redirect_stdout(stdout):
                            code = main()

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 1)
        self.assertEqual(payload['status'], 'fail')
        self.assertEqual(payload['error'], 'bad config')

    def test_build_config_fingerprints_records_config_hashes(self):
        fingerprints = build_config_fingerprints(Path('.'))

        self.assertEqual(set(fingerprints), {
            'config/thresholds.json',
            'config/risk_limits.json',
            'config/automation_gate.json',
            'config/execution_venues.json',
            'config/verification_expectations.json',
        })
        for digest in fingerprints.values():
            self.assertEqual(len(digest), 64)

    def test_build_config_fingerprints_reports_read_error(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'config/thresholds.json').mkdir(parents=True)

            with self.assertRaisesRegex(ValueError, r'invalid fingerprint input: config/thresholds\.json:'):
                build_config_fingerprints(root)

    def test_build_artifact_fingerprints_records_pipeline_hashes(self):
        fingerprints = build_artifact_fingerprints(Path('.'))

        self.assertEqual(set(fingerprints), {
            'data/pipeline/candidate_events.jsonl',
            'data/pipeline/daily_summary.md',
            'data/pipeline/telegram_dry_run.txt',
            'data/pipeline/reviewed_candidate_events.jsonl',
            'data/pipeline/outcome_analysis.md',
            'data/pipeline/trade_plans.json',
            'data/pipeline/automation_gate.md',
        })
        for digest in fingerprints.values():
            self.assertEqual(len(digest), 64)

    def test_build_artifact_fingerprints_reports_read_error(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'data/pipeline/daily_summary.md').mkdir(parents=True)

            with self.assertRaisesRegex(ValueError, r'invalid fingerprint input: data/pipeline/daily_summary\.md:'):
                build_artifact_fingerprints(root)

    def test_build_report_includes_config_fingerprints(self):
        report = build_report(
            [VerificationStep('doctor', True, [])],
            {'config/thresholds.json': 'abc'},
        )

        self.assertEqual(report['config_fingerprints'], {'config/thresholds.json': 'abc'})

    def test_build_report_includes_artifact_fingerprints(self):
        report = build_report(
            [VerificationStep('pipeline', True, [])],
            artifact_fingerprints={'data/pipeline/daily_summary.md': 'def'},
        )

        self.assertEqual(report['artifact_fingerprints'], {'data/pipeline/daily_summary.md': 'def'})

    def test_build_operational_summary_reads_pipeline_outputs(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / 'data/pipeline'
            output_dir.mkdir(parents=True)
            (output_dir / 'reviewed_candidate_events.jsonl').write_text(
                '\n'.join([
                    json.dumps({'decision': 'alert', 'outcome': {'reviewed': True}}),
                    json.dumps({'decision': 'watch', 'outcome': {'reviewed': False}}),
                    json.dumps({'decision': 'reject', 'outcome': {'reviewed': False}}),
                ]) + '\n',
                encoding='utf-8',
            )
            (output_dir / 'automation_gate.md').write_text('Status: blocked\n', encoding='utf-8')

            summary = build_operational_summary(root)

        self.assertEqual(summary['candidate_count'], 3)
        self.assertEqual(summary['decisions'], {'alert': 1, 'watch': 1, 'reject': 1})
        self.assertEqual(summary['outcomes'], {'pending': 2, 'reviewed': 1})
        self.assertEqual(summary['automation_gate_status'], 'blocked')

    def test_build_operational_summary_reports_invalid_event_json(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / 'data/pipeline'
            output_dir.mkdir(parents=True)
            (output_dir / 'candidate_events.jsonl').write_text('{"decision":"alert"}\nnot-json\n', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, r'candidate_events\.jsonl:2: invalid operational summary events JSON:'):
                build_operational_summary(root)

    def test_build_operational_summary_reports_invalid_event_utf8(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / 'data/pipeline'
            output_dir.mkdir(parents=True)
            (output_dir / 'candidate_events.jsonl').write_bytes(b'\xff')

            with self.assertRaisesRegex(ValueError, r'candidate_events\.jsonl: invalid operational summary events UTF-8:'):
                build_operational_summary(root)

    def test_build_operational_summary_reports_event_read_error(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / 'data/pipeline'
            output_dir.mkdir(parents=True)
            (output_dir / 'candidate_events.jsonl').mkdir()

            with self.assertRaisesRegex(ValueError, r'candidate_events\.jsonl: invalid operational summary events read:'):
                build_operational_summary(root)

    def test_build_operational_summary_rejects_non_object_event(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / 'data/pipeline'
            output_dir.mkdir(parents=True)
            (output_dir / 'candidate_events.jsonl').write_text('[]\n', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, r'candidate_events\.jsonl:1: invalid operational summary events event: expected object'):
                build_operational_summary(root)

    def test_build_operational_summary_reports_invalid_gate_utf8(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / 'data/pipeline'
            output_dir.mkdir(parents=True)
            (output_dir / 'candidate_events.jsonl').write_text('{"decision":"reject"}\n', encoding='utf-8')
            (output_dir / 'automation_gate.md').write_bytes(b'\xff')

            with self.assertRaisesRegex(ValueError, r'automation_gate\.md: invalid operational summary gate UTF-8:'):
                build_operational_summary(root)

    def test_build_operational_summary_reports_gate_read_error(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / 'data/pipeline'
            output_dir.mkdir(parents=True)
            (output_dir / 'candidate_events.jsonl').write_text('{"decision":"reject"}\n', encoding='utf-8')
            (output_dir / 'automation_gate.md').mkdir()

            with self.assertRaisesRegex(ValueError, r'automation_gate\.md: invalid operational summary gate read:'):
                build_operational_summary(root)

    def test_build_report_includes_operational_summary(self):
        report = build_report(
            [VerificationStep('pipeline', True, [])],
            operational_summary={'candidate_count': 3},
        )

        self.assertEqual(report['operational_summary'], {'candidate_count': 3})

    def test_check_operational_expectations_accepts_matching_summary(self):
        summary = {
            'automation_gate_status': 'blocked',
            'candidate_count': 3,
            'decisions': {'alert': 1, 'watch': 1, 'reject': 1},
            'outcomes': {'pending': 2, 'reviewed': 1},
        }

        failures = check_operational_expectations(summary, {
            'automation_gate_status': 'blocked',
            'candidate_count': 3,
            'decisions': {'alert': 1, 'watch': 1, 'reject': 1},
            'outcomes': {'pending': 2, 'reviewed': 1},
        })

        self.assertEqual(failures, [])

    def test_check_operational_expectations_reports_drift(self):
        summary = {
            'automation_gate_status': 'blocked',
            'candidate_count': 3,
            'decisions': {'alert': 1, 'watch': 1, 'reject': 1},
            'outcomes': {'pending': 2, 'reviewed': 1},
        }

        failures = check_operational_expectations(summary, {
            'automation_gate_status': 'ready',
            'candidate_count': 4,
            'decisions': {'alert': 2},
        })

        self.assertEqual(failures, [
            "automation_gate_status expected 'ready', got 'blocked'",
            'candidate_count expected 4, got 3',
            'decisions.alert expected 2, got 1',
        ])

    def test_validate_verification_expectations_rejects_bad_shape(self):
        failures = validate_verification_expectations({
            'automation_gate_status': 1,
            'candidate_count': '4',
            'decisions': {'alert': 1, 'watch': -1},
            'outcomes': {'pending': 2},
        })

        self.assertEqual(failures, [
            'automation_gate_status must be a string',
            'candidate_count must be a non-negative integer',
            'decisions.watch must be a non-negative integer',
            'decisions.reject must be a non-negative integer',
            'outcomes.reviewed must be a non-negative integer',
        ])

    def test_load_verification_expectations_loads_valid_config(self):
        expectations = load_verification_expectations(Path('config/verification_expectations.json'))

        self.assertEqual(expectations['automation_gate_status'], 'blocked')
        self.assertEqual(expectations['candidate_count'], 4)

    def test_invalid_verification_expectations_json_reports_path_and_line(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'verification_expectations.json'
            path.write_text('{\nnot-json\n', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, r'verification_expectations\.json:2: invalid verification expectations JSON:'):
                load_verification_expectations(path)

    def test_invalid_verification_expectations_utf8_reports_path(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'verification_expectations.json'
            path.write_bytes(b'\xff')

            with self.assertRaisesRegex(ValueError, r'verification_expectations\.json: invalid verification expectations UTF-8:'):
                load_verification_expectations(path)

    def test_verification_expectations_read_error_reports_path(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'verification_expectations.json'
            path.mkdir()

            with self.assertRaisesRegex(ValueError, r'verification_expectations\.json: invalid verification expectations read:'):
                load_verification_expectations(path)


if __name__ == '__main__':
    unittest.main()
