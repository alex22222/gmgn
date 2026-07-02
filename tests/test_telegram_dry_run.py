import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from gmgn_monitor.telegram_dry_run import build_messages, format_message, main


def event(decision='alert'):
    return {
        'decision': decision,
        'symbol': 'GOOD',
        'chain': 'solana',
        'score': 90,
        'token_address': 'Good111111111111111111111111111111111111111',
        'market_cap': 69000.0,
        'liquidity': 140.0,
        'reasons': ['liquidity meets minimum', '5m volume meets minimum'],
    }


class TelegramDryRunTest(unittest.TestCase):
    def test_formats_alert_message(self):
        message = format_message(event('alert'))

        self.assertIn('[ALERT] GOOD on solana', message)
        self.assertIn('Score: 90', message)
        self.assertIn('- liquidity meets minimum', message)

    def test_formats_watch_message(self):
        message = format_message(event('watch'))

        self.assertIn('[WATCH] GOOD on solana', message)

    def test_suppresses_reject_message(self):
        self.assertIsNone(format_message(event('reject')))

    def test_build_messages_keeps_only_alert_and_watch(self):
        messages = build_messages([event('alert'), event('reject'), event('watch')])

        self.assertEqual(len(messages), 2)
        self.assertIn('[ALERT]', messages[0])
        self.assertIn('[WATCH]', messages[1])

    def test_main_writes_dry_run_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / 'events.jsonl'
            output_path = Path(tmp_dir) / 'telegram.txt'
            input_path.write_text(json.dumps(event('alert')) + '\n' + json.dumps(event('reject')) + '\n', encoding='utf-8')

            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch('sys.argv', ['telegram_dry_run', '--input', str(input_path), '--output', str(output_path)]):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = main()

            content = output_path.read_text(encoding='utf-8')

        self.assertEqual(code, 0)
        self.assertEqual(stderr.getvalue(), '')
        self.assertIn('wrote 1 dry-run messages', stdout.getvalue())
        self.assertIn('[ALERT] GOOD', content)
        self.assertNotIn('[REJECT]', content)

    def test_main_reports_invalid_input_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / 'events.jsonl'
            output_path = Path(tmp_dir) / 'telegram.txt'
            input_path.write_text('not-json\n', encoding='utf-8')

            stderr = io.StringIO()
            with patch('sys.argv', ['telegram_dry_run', '--input', str(input_path), '--output', str(output_path)]):
                with redirect_stderr(stderr):
                    code = main()

        self.assertEqual(code, 2)
        self.assertIn('invalid dry-run input:', stderr.getvalue())
        self.assertNotIn('Traceback', stderr.getvalue())
        self.assertFalse(output_path.exists())

    def test_main_reports_write_error_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / 'events.jsonl'
            output_path = Path(tmp_dir) / 'telegram.txt'
            input_path.write_text(json.dumps(event('alert')) + '\n', encoding='utf-8')
            output_path.mkdir()

            stderr = io.StringIO()
            with patch('sys.argv', ['telegram_dry_run', '--input', str(input_path), '--output', str(output_path)]):
                with redirect_stderr(stderr):
                    code = main()

        self.assertEqual(code, 2)
        self.assertIn('failed to write dry-run messages:', stderr.getvalue())
        self.assertNotIn('Traceback', stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
