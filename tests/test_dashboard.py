import json
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from gmgn_monitor.dashboard import (
    ACTIONS,
    ACTION_LOCK,
    DashboardHandler,
    build_action_command,
    build_dashboard_payload,
    find_available_port,
    main,
    make_handler,
    run_action,
)


class DashboardTest(unittest.TestCase):
    def test_action_commands_are_whitelisted_python_modules(self):
        command = build_action_command('status')

        self.assertEqual(command[1:3], ['-m', 'gmgn_monitor.status'])
        self.assertIn('status', ACTIONS)

        with self.assertRaises(ValueError):
            build_action_command('rm -rf')

    def test_find_available_port_skips_used_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as used:
            used.bind(('127.0.0.1', 0))
            used.listen()
            occupied_port = used.getsockname()[1]

            port = find_available_port('127.0.0.1', occupied_port, occupied_port + 2)

        self.assertNotEqual(port, occupied_port)

    def test_dashboard_main_reports_start_failure_without_traceback(self):
        stderr = StringIO()
        with patch.object(sys, 'argv', ['dashboard']), \
                patch('sys.stderr', stderr), \
                patch('gmgn_monitor.dashboard.serve', side_effect=OSError('no available port')):
            code = main()

        self.assertEqual(code, 2)
        self.assertIn('failed to start GMGN dashboard: no available port', stderr.getvalue())
        self.assertNotIn('Traceback', stderr.getvalue())

    def test_dashboard_payload_includes_status_actions_and_outputs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'fixtures').mkdir(parents=True)
            (root / 'data/pipeline').mkdir(parents=True)
            (root / 'fixtures/candidates.jsonl').write_text('{"symbol":"A"}\n{"symbol":"B"}\n', encoding='utf-8')
            (root / 'data/pipeline/daily_summary.md').write_text('# Summary\n', encoding='utf-8')

            payload = build_dashboard_payload(root)

        self.assertIn('status', payload)
        self.assertIn('actions', payload)
        self.assertEqual(payload['actions'][0]['label'], '刷新状态')
        self.assertEqual(payload['data_sources'][0]['name'], '本地 JSONL 候选数据')
        self.assertEqual(payload['data_sources'][0]['health'], '可用，2 条记录')
        self.assertEqual(payload['user_flow'][0]['action'], '刷新状态')
        self.assertEqual(payload['outputs']['daily_summary']['content'], '# Summary\n')

    def test_dashboard_source_health_reports_invalid_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'fixtures').mkdir(parents=True)
            (root / 'fixtures/candidates.jsonl').write_text('{"symbol":"A"}\nnot json\n', encoding='utf-8')

            payload = build_dashboard_payload(root)

        self.assertIn('格式错误，第 2 行', payload['data_sources'][0]['health'])

    def test_dashboard_source_health_reports_non_object_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'fixtures').mkdir(parents=True)
            (root / 'fixtures/candidates.jsonl').write_text('[]\n', encoding='utf-8')

            payload = build_dashboard_payload(root)

        self.assertEqual(payload['data_sources'][0]['health'], '格式错误，第 1 行不是对象')

    def test_dashboard_source_health_reports_invalid_utf8_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'fixtures').mkdir(parents=True)
            (root / 'fixtures/candidates.jsonl').write_bytes(b'\xff')

            payload = build_dashboard_payload(root)

        self.assertEqual(payload['data_sources'][0]['health'], '格式错误，不是有效 UTF-8')

    def test_dashboard_source_health_reports_jsonl_read_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'fixtures/candidates.jsonl').mkdir(parents=True)

            payload = build_dashboard_payload(root)

        self.assertIn('读取失败', payload['data_sources'][0]['health'])

    def test_dashboard_dexscreener_health_reports_payload_pairs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'fixtures').mkdir(parents=True)
            (root / 'data').mkdir(parents=True)
            (root / 'fixtures/dexscreener_search_sample.json').write_text('{"pairs":[{}]}', encoding='utf-8')
            (root / 'data/dexscreener_candidates.jsonl').write_text('{"symbol":"DEX"}\n', encoding='utf-8')
            (root / 'data/dexscreener_events.jsonl').write_text('{"symbol":"DEX"}\n', encoding='utf-8')

            payload = build_dashboard_payload(root)

        health = payload['data_sources'][2]['health']
        self.assertIn('dexscreener_search_sample.json: 可用，1 个 pairs', health)
        self.assertIn('dexscreener_candidates.jsonl: 可用，1 条记录', health)

    def test_dashboard_dexscreener_health_reports_invalid_payload_pairs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'fixtures').mkdir(parents=True)
            (root / 'fixtures/dexscreener_search_sample.json').write_text('{"pairs":{}}', encoding='utf-8')

            payload = build_dashboard_payload(root)

        self.assertIn('dexscreener_search_sample.json: 格式错误，pairs 不是列表', payload['data_sources'][2]['health'])

    def test_dashboard_dexscreener_health_reports_invalid_utf8_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'fixtures').mkdir(parents=True)
            (root / 'data').mkdir(parents=True)
            (root / 'fixtures/dexscreener_search_sample.json').write_text('{"pairs":[]}', encoding='utf-8')
            (root / 'data/dexscreener_candidates.jsonl').write_bytes(b'\xff')

            payload = build_dashboard_payload(root)

        self.assertIn('dexscreener_candidates.jsonl: 格式错误，不是有效 UTF-8', payload['data_sources'][2]['health'])

    def test_dashboard_dexscreener_health_reports_payload_read_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'fixtures/dexscreener_search_sample.json').mkdir(parents=True)

            payload = build_dashboard_payload(root)

        self.assertIn('dexscreener_search_sample.json: 读取失败', payload['data_sources'][2]['health'])

    def test_dashboard_planned_doc_health_reports_non_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'SAFETY_ENRICHMENT.md').mkdir()

            payload = build_dashboard_payload(root)

        self.assertEqual(payload['data_sources'][4]['health'], '读取失败：不是文件')

    def test_dashboard_output_invalid_utf8_reports_read_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'data/pipeline').mkdir(parents=True)
            (root / 'data/pipeline/daily_summary.md').write_bytes(b'\xff')

            payload = build_dashboard_payload(root)

        self.assertEqual(payload['outputs']['daily_summary']['content'], '')
        self.assertEqual(payload['outputs']['daily_summary']['read_error'], '输出文件不是有效 UTF-8')

    def test_dashboard_output_read_error_reports_read_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'data/pipeline/daily_summary.md').mkdir(parents=True)

            payload = build_dashboard_payload(root)

        self.assertEqual(payload['outputs']['daily_summary']['content'], '')
        self.assertIn('输出文件读取失败', payload['outputs']['daily_summary']['read_error'])

    def test_dashboard_action_timeout_returns_structured_failure(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            with patch('gmgn_monitor.dashboard.subprocess.run') as run:
                run.side_effect = subprocess.TimeoutExpired(['python3'], timeout=1)

                result = run_action(root, 'status', timeout_seconds=1)

        self.assertFalse(result['ok'])
        self.assertEqual(result['returncode'], None)
        self.assertIn('超时', result['stderr'])
        self.assertIn('dashboard', result)

    def test_dashboard_action_decode_error_returns_structured_failure(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            with patch('gmgn_monitor.dashboard.subprocess.run') as run:
                run.side_effect = UnicodeDecodeError('utf-8', b'\xff', 0, 1, 'invalid start byte')

                result = run_action(root, 'status')

        self.assertFalse(result['ok'])
        self.assertEqual(result['returncode'], None)
        self.assertIn('命令输出不是有效文本', result['stderr'])
        self.assertIn('dashboard', result)

    def test_dashboard_action_start_error_returns_structured_failure(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            with patch('gmgn_monitor.dashboard.subprocess.run') as run:
                run.side_effect = OSError('cannot start')

                result = run_action(root, 'status')

        self.assertFalse(result['ok'])
        self.assertEqual(result['returncode'], None)
        self.assertIn('命令启动失败', result['stderr'])
        self.assertIn('cannot start', result['stderr'])
        self.assertIn('dashboard', result)

    def test_dashboard_action_rejects_concurrent_run(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            ACTION_LOCK.acquire()
            try:
                result = run_action(root, 'status')
            finally:
                ACTION_LOCK.release()

        self.assertFalse(result['ok'])
        self.assertEqual(result['returncode'], None)
        self.assertIn('已有命令正在运行', result['stderr'])
        self.assertIn('dashboard', result)

    def test_handler_serves_index_and_payload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'data/pipeline').mkdir(parents=True)
            (root / 'data/pipeline/automation_gate.md').write_text('Status: blocked\n', encoding='utf-8')
            handler = make_handler(root)
            server = DashboardHandler.create_server('127.0.0.1', 0, handler)
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=5) as response:
                    html = response.read().decode('utf-8')
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/status', timeout=5) as response:
                    payload = json.loads(response.read().decode('utf-8'))
            finally:
                server.shutdown()
                server.server_close()

        self.assertIn('GMGN 扫链监控', html)
        self.assertIn('用户执行流程', html)
        self.assertIn('数据源状态', html)
        self.assertIn('运行状态', html)
        self.assertIn('summaryWarning', html)
        self.assertIn('验证报告 JSON 格式错误', html)
        self.assertIn('验证报告读取失败：', html)
        self.assertIn('读取失败：', html)
        self.assertEqual(payload['outputs']['automation_gate']['content'], 'Status: blocked\n')
        self.assertEqual(payload['data_sources'][2]['alertable'], '默认不可以')
        self.assertIn('dexscreener_search_sample.json', payload['data_sources'][2]['health'])
        self.assertEqual(payload['user_flow'][-1]['action'], '人工计划 / 自动化安全门')

    def test_handler_unknown_action_returns_structured_failure(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            handler = make_handler(root)
            server = DashboardHandler.create_server('127.0.0.1', 0, handler)
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            request = urllib.request.Request(
                f'http://127.0.0.1:{port}/api/actions/not_allowed',
                method='POST',
            )
            try:
                with self.assertRaises(urllib.error.HTTPError) as context:
                    urllib.request.urlopen(request, timeout=5)
                error = context.exception
                try:
                    body = error.read().decode('utf-8')
                finally:
                    error.close()
            finally:
                server.shutdown()
                server.server_close()

        payload = json.loads(body)
        self.assertEqual(context.exception.code, 400)
        self.assertFalse(payload['ok'])
        self.assertEqual(payload['command'], '')
        self.assertEqual(payload['returncode'], None)
        self.assertEqual(payload['stdout'], '')
        self.assertIn('unknown dashboard action', payload['stderr'])
        self.assertIn('dashboard', payload)


if __name__ == '__main__':
    unittest.main()
